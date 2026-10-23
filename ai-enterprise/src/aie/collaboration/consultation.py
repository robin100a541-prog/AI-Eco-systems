"""Samråd (FR-11, konstitutionen §20 steg 5): rätt roller yttrar sig innan ett beslut fattas.

Vilka roller som måste yttra sig avgörs av koden när samrådet öppnas, inte av den som frågar:

| Villkor                                   | Krävs                                   |
|-------------------------------------------|-----------------------------------------|
| Ett belopp finns (> 0)                     | CFO (finans, §11)                       |
| Riskklass medium, high eller critical      | CRO (risk, §17, §24)                    |
| Juridik, avtal, plattformsvillkor eller skatt | Compliance (§6, SR-16)              |
| Belopp > HUMAN_APPROVAL_THRESHOLD, gräns saknas, eller riskklass critical | grundarna (D-019) |

Saknas `HUMAN_APPROVAL_THRESHOLD` räknas varje belopp som över gränsen. En saknad gräns
betyder blockera, aldrig obegränsat (ER-02).

Regler:
- Bara grundare, CEO, kontrollfunktioner och departementschefer (nivå 1–3) kan öppna ett samråd.
- Ett yttrande lämnas av en aktiv agent vars roll krävs i samrådet: en roll, ett yttrande.
  Yttrandet ändras aldrig. Det måste ha en motivering, och en invändning måste ha underlag.
- Samrådet är **klart** när alla krävda roller har yttrat sig. Att alla är överens krävs inte
  (§20: samråd innebär inte att alla måste vara överens). Invändningarna lämnas till
  hanteringen av oenighet (§21) och beslutsloggen (FR-10, FR-12), som Robin bygger.
- Varje öppnat samråd och varje yttrande skrivs till audit-loggen.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ..agents import ACTING_STATES, LEVEL_HEAD, AgentRegistry
from ..audit import AuditLog
from ..authorization import Permissions
from ..config import Money
from ..memory import Database


class RiskClass(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Position(str, Enum):
    SUPPORT = "support"
    OBJECT = "object"
    ABSTAIN = "abstain"


CFO, CRO, COMPLIANCE = "cfo", "cro", "compliance"
_EVIDENCE = re.compile(r"(ledger|task|audit|file|url|decision|report):\S+")  # samma idé som reporting


class ConsultationError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class Requirement:
    roles: tuple[str, ...]
    requires_founders: bool


def required_for(
    amount: Money | None, risk_class: RiskClass, legal: bool, approval_threshold: Money | None
) -> Requirement:
    """Ren funktion: vilka som måste yttra sig. Testbar utan databas."""
    roles: list[str] = []
    founders = risk_class is RiskClass.CRITICAL
    if amount is not None and amount.amount_minor > 0:
        roles.append(CFO)
        if approval_threshold is None or amount.amount_minor > approval_threshold.amount_minor:
            founders = True
    if risk_class in (RiskClass.MEDIUM, RiskClass.HIGH, RiskClass.CRITICAL):
        roles.append(CRO)
    if legal:
        roles.append(COMPLIANCE)
    return Requirement(tuple(roles), founders)


@dataclass(frozen=True, slots=True)
class Opinion:
    role: str
    agent_id: str
    position: Position
    reasoning: str
    evidence: tuple[str, ...]
    at: str


@dataclass(frozen=True, slots=True)
class Consultation:
    consultation_id: int
    subject: str  # t.ex. "task:12" eller "decision:3"
    question: str
    opened_by: str
    amount: Money | None
    risk_class: RiskClass
    legal: bool
    required_roles: tuple[str, ...]
    requires_founders: bool
    opinions: tuple[Opinion, ...] = ()

    @property
    def missing_roles(self) -> tuple[str, ...]:
        answered = {o.role for o in self.opinions}
        return tuple(r for r in self.required_roles if r not in answered)

    @property
    def complete(self) -> bool:
        return not self.missing_roles

    @property
    def objections(self) -> tuple[Opinion, ...]:
        return tuple(o for o in self.opinions if o.position is Position.OBJECT)

    @property
    def unanimous(self) -> bool:
        return self.complete and all(o.position is Position.SUPPORT for o in self.opinions)


class ConsultationBoard:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions: Permissions,
        audit: AuditLog,
        founders: frozenset[str],
        approval_threshold: Money | None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._threshold = approval_threshold
        self._clock = clock

    def open(
        self,
        actor: str,
        subject: str,
        question: str,
        risk_class: RiskClass,
        amount: Money | None = None,
        legal: bool = False,
    ) -> Consultation:
        self._require_opener(actor)
        if not subject.strip() or not question.strip():
            raise ConsultationError("ett samråd behöver ämne och fråga")
        if amount is not None:
            if isinstance(amount.amount_minor, bool) or not isinstance(amount.amount_minor, int) or amount.amount_minor < 0:
                raise ConsultationError("beloppet måste vara ett heltal >= 0 i minsta enhet (D-006)")
            if self._threshold is not None and amount.currency != self._threshold.currency:
                raise ConsultationError(
                    f"valutan {amount.currency} matchar inte gränsernas valuta {self._threshold.currency} (ER-15)"
                )
        req = required_for(amount, risk_class, legal, self._threshold)
        if not req.roles and not req.requires_founders:
            raise ConsultationError("inget samråd behövs: inget belopp, låg risk och ingen juridisk fråga")
        now = self._clock()
        with self._db.transaction() as tx:
            cursor = tx.execute(
                "INSERT INTO consultations (subject, question, opened_by, amount_minor, currency, risk_class, legal, "
                "required_roles, requires_founders, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (subject, question, actor,
                 amount.amount_minor if amount else None, amount.currency if amount else None,
                 risk_class.value, int(legal), json.dumps(list(req.roles)), int(req.requires_founders), now),
            )
            consultation = Consultation(cursor.lastrowid, subject, question, actor, amount, risk_class, legal,
                                        req.roles, req.requires_founders)
        self._audit.append("collaboration", "consultation.opened", {
            "consultation_id": consultation.consultation_id, "subject": subject, "opened_by": actor,
            "risk_class": risk_class.value, "required_roles": list(req.roles),
            "requires_founders": req.requires_founders,
        })
        return consultation

    def respond(
        self, agent_id: str, consultation_id: int, position: Position, reasoning: str, evidence: tuple[str, ...] = ()
    ) -> Consultation:
        consultation = self.get(consultation_id)
        if consultation is None:
            raise ConsultationError(f"samråd {consultation_id} finns inte")
        agent = self._registry.get(agent_id)
        if agent is None or agent.state not in ACTING_STATES:
            raise ConsultationError(f"{agent_id!r} finns inte eller får inte agera just nu")
        if agent.role not in consultation.required_roles:
            raise ConsultationError(
                f"rollen {agent.role} ingår inte i samråd {consultation_id} (krävs: {', '.join(consultation.required_roles)})"
            )
        if agent.role not in consultation.missing_roles:
            raise ConsultationError(f"rollen {agent.role} har redan yttrat sig; yttranden ändras aldrig")
        if not reasoning.strip():
            raise ConsultationError("ett yttrande behöver en saklig motivering (§20 steg 5)")
        bad = [e for e in evidence if not _EVIDENCE.fullmatch(e)]
        if bad:
            raise ConsultationError(f"ogiltigt underlag {bad}")
        if position is Position.OBJECT and not evidence:
            raise ConsultationError("en invändning behöver underlag (§21: vilka fakta stöder ståndpunkten)")
        now = self._clock()
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO consultation_opinions (consultation_id, role, agent_id, position, reasoning, evidence, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (consultation_id, agent.role, agent_id, position.value, reasoning, json.dumps(list(evidence)), now),
            )
        self._audit.append("collaboration", "consultation.opinion", {
            "consultation_id": consultation_id, "role": agent.role, "agent_id": agent_id,
            "position": position.value, "evidence": list(evidence),
        })
        return self.get(consultation_id)

    def get(self, consultation_id: int) -> Consultation | None:
        row = self._db.connection.execute(
            "SELECT consultation_id, subject, question, opened_by, amount_minor, currency, risk_class, legal, "
            "required_roles, requires_founders FROM consultations WHERE consultation_id = ?",
            (consultation_id,),
        ).fetchone()
        if row is None:
            return None
        cid, subject, question, opened_by, amount_minor, currency, risk, legal, roles, founders = row
        opinions = tuple(
            Opinion(role, agent, Position(pos), reasoning, tuple(json.loads(ev)), at)
            for role, agent, pos, reasoning, ev, at in self._db.connection.execute(
                "SELECT role, agent_id, position, reasoning, evidence, at FROM consultation_opinions "
                "WHERE consultation_id = ? ORDER BY id",
                (cid,),
            )
        )
        amount = None if amount_minor is None else Money(amount_minor, currency)
        return Consultation(cid, subject, question, opened_by, amount, RiskClass(risk), bool(legal),
                            tuple(json.loads(roles)), bool(founders), opinions)

    def _require_opener(self, actor: str) -> None:
        if actor in self._founders:
            return
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise ConsultationError(f"{actor!r} finns inte eller får inte agera just nu")
        if self._permissions.roles[agent.role].level > LEVEL_HEAD:
            raise ConsultationError("bara grundare, CEO, kontrollfunktioner och departementschefer öppnar samråd")
