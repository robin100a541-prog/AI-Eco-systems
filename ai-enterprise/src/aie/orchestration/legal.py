"""Juridisk eller avtalsmässig konflikt (SR-16, konstitutionen §6).

> När en agent upptäcker en möjlig juridisk eller avtalsmässig konflikt ska den avbryta den
> berörda åtgärden och skicka frågan till ansvarig kontrollfunktion.

`LegalDesk.raise_conflict(...)` gör tre saker, i den här ordningen:
1. **Öppnar ett samråd** med Compliance och CRO (riskklass high, juridisk fråga).
2. Sparar en **hållning** för uppgiften (migration 11) som pekar på samrådet. Från den stunden
   vägrar `TaskBoard` att starta, tilldela, blockera eller slutföra uppgiften, eftersom den
   läser hållningen direkt ur databasen.
3. **Blockerar** uppgiften, oavsett vem som äger den.

Vem som helst som får agera, även en arbetsagent, och grundarna kan flagga. Det ska vara
lätt att stoppa och svårt att fortsätta (§17: osäkerhet räknas som risk).

Hållningen släpps (`release`) bara av en aktiv Compliance-agent eller en grundare:
- `cleared`: uppgiften får fortsätta. Det kräver att samrådet är klart och att Compliance inte
  har invänt. Ingen, inte heller en grundare, kan släppa förbi en invändning från Compliance
  (§6: ingen ekonomisk målsättning får åsidosätta lagar). Vill man ändå gå vidare krävs ett
  nytt underlag och en ny flaggning.
- `cancelled`: uppgiften avbryts.
Allt loggas i audit-loggen.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ..agents import ACTING_STATES, AgentRegistry
from ..audit import AuditLog
from ..collaboration import ConsultationBoard, Position
from ..memory import Database
from .tasks import FINAL, Task, TaskBoard

COMPLIANCE = "compliance"
OUTCOMES = ("cleared", "cancelled")
_EVIDENCE = re.compile(r"(ledger|task|audit|file|url|decision|report):\S+")


class LegalError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class LegalHold:
    hold_id: int
    task_id: int
    description: str
    evidence: tuple[str, ...]
    raised_by: str
    consultation_id: int
    released_by: str | None = None
    outcome: str | None = None
    release_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.outcome is None


class LegalDesk:
    def __init__(
        self,
        db: Database,
        board: TaskBoard,
        consultations: ConsultationBoard,
        registry: AgentRegistry,
        audit: AuditLog,
        founders: frozenset[str],
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._db = db
        self._board = board
        self._consultations = consultations
        self._registry = registry
        self._audit = audit
        self._founders = frozenset(founders)
        self._clock = clock

    def raise_conflict(self, actor: str, task_id: int, description: str, evidence: tuple[str, ...]) -> LegalHold:
        self._require_actor(actor)
        if not description.strip():
            raise LegalError("beskriv konflikten")
        bad = [e for e in evidence if not _EVIDENCE.fullmatch(e)]
        if not evidence or bad:
            raise LegalError(f"underlag krävs (t.ex. url:<villkor>), fick {list(evidence)}")
        task = self._board.get(task_id)
        if task is None:
            raise LegalError(f"uppgift {task_id} finns inte")
        if task.status in FINAL:
            raise LegalError(f"uppgift {task_id} är redan {task.status.value}")
        if self.active_hold(task_id) is not None:
            raise LegalError(f"uppgift {task_id} är redan hållen för juridisk granskning")

        consultation = self._consultations.open_for_legal_review(f"task:{task_id}", description)
        now = self._clock()
        with self._db.transaction() as tx:
            cursor = tx.execute(
                "INSERT INTO legal_holds (task_id, description, evidence, raised_by, consultation_id, raised_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, description, json.dumps(list(evidence)), actor, consultation.consultation_id, now),
            )
            hold = LegalHold(cursor.lastrowid, task_id, description, tuple(evidence), actor, consultation.consultation_id)
        self._board._apply_legal_hold(task_id, actor, f"juridisk hållning #{hold.hold_id}: {description}")
        self._audit.append("legal", "legal.conflict_raised", {
            "hold_id": hold.hold_id, "task_id": task_id, "raised_by": actor,
            "consultation_id": consultation.consultation_id, "evidence": list(evidence),
        })
        return hold

    def release(self, actor: str, hold_id: int, outcome: str, reason: str) -> Task:
        if outcome not in OUTCOMES:
            raise LegalError(f"utfallet måste vara {' eller '.join(OUTCOMES)}")
        if not reason.strip():
            raise LegalError("en motivering krävs")
        if actor not in self._founders:
            agent = self._registry.get(actor)
            if agent is None or agent.role != COMPLIANCE or agent.state not in ACTING_STATES:
                raise LegalError("bara Compliance eller en grundare kan släppa en juridisk hållning (SR-16)")
        hold = self.get(hold_id)
        if hold is None or not hold.active:
            raise LegalError(f"hållning #{hold_id} finns inte eller är redan släppt")
        if outcome == "cleared":
            consultation = self._consultations.get(hold.consultation_id)
            if not consultation.complete:
                raise LegalError(f"samråd {consultation.consultation_id} väntar på: {', '.join(consultation.missing_roles)}")
            if any(o.role == COMPLIANCE and o.position is Position.OBJECT for o in consultation.opinions):
                raise LegalError("Compliance har invänt; uppgiften kan inte fortsätta på det här underlaget (§6)")
        with self._db.transaction() as tx:
            tx.execute(
                "UPDATE legal_holds SET released_by = ?, released_at = ?, outcome = ?, release_reason = ? WHERE hold_id = ?",
                (actor, self._clock(), outcome, reason, hold_id),
            )
        task = self._board._release_legal_hold(hold.task_id, actor, f"hållning #{hold_id} {outcome}: {reason}",
                                               cancel=outcome == "cancelled")
        self._audit.append("legal", f"legal.{outcome}", {"hold_id": hold_id, "task_id": hold.task_id, "by": actor})
        return task

    def get(self, hold_id: int) -> LegalHold | None:
        return self._one("WHERE hold_id = ?", (hold_id,))

    def active_hold(self, task_id: int) -> LegalHold | None:
        return self._one("WHERE task_id = ? AND released_at IS NULL", (task_id,))

    def _one(self, where: str, params: tuple) -> LegalHold | None:
        row = self._db.connection.execute(
            "SELECT hold_id, task_id, description, evidence, raised_by, consultation_id, released_by, outcome, "
            f"release_reason FROM legal_holds {where}",
            params,
        ).fetchone()
        if row is None:
            return None
        hold_id, task_id, description, evidence, raised_by, cid, released_by, outcome, reason = row
        return LegalHold(hold_id, task_id, description, tuple(json.loads(evidence)), raised_by, cid,
                         released_by, outcome, reason)

    def _require_actor(self, actor: str) -> None:
        if actor in self._founders:
            return
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise LegalError(f"{actor!r} finns inte eller får inte agera just nu")
