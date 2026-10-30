"""Sparade bedömningar och den hårda spärren "simulera före start" (PR 6, D-058).

En **bedömning** gäller ett initiativ på en plattform med exakt de parametrar som står i den. Parametrarna
är initiativets och plattformens data i registret, och `params_hash` är SHA-256 av dem. Ändras något i
initiativet eller plattformen efter godkännandet gäller bedömningen inte längre, och en ny måste göras.

Spärren gäller i `Register` och i budgetmotorn:
- Ett initiativ kan bara bli `approved` eller `active`, och bara få utgifter, med en **godkänd** bedömning
  som är **redo** och har samma `params_hash` som initiativet och plattformen har nu.
- En plattform kan bara bli `approved` eller `active` med minst en sådan bedömning för ett initiativ på den.

Bara en grundare godkänner en bedömning, och bara om den är redo (D-048 och pessimistiskt scenario,
`readiness.assess_initiative`). En bedömning av typen `scenario` finns bara i simuleringens egna
databaser: en scenariokörning är själv testet av scenariots antaganden, och den kan aldrig godkännas i prod.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..audit import AuditLog
from ..memory import Database


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def params_hash(initiative: dict, platform: dict) -> str:
    text = json.dumps({"initiative": initiative, "platform": platform}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AssessmentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Assessment:
    assessment_id: int
    kind: str
    initiative: str
    platform: str
    params_hash: str
    params: dict
    result: dict
    ready: bool
    actor: str
    at: str
    decision: str | None = None  # approved | rejected | None
    decided_by: str | None = None


class AssessmentStore:
    def __init__(self, db: Database, audit: AuditLog, founders: frozenset[str], environment: str = "sim",
                 clock: Callable[[], str] = _now) -> None:
        self._db = db
        self._audit = audit
        self._founders = frozenset(founders)
        self._environment = environment
        self._clock = clock

    def record(self, actor: str, initiative: str, platform: str, initiative_data: dict, platform_data: dict,
               result: dict, ready: bool, kind: str = "simulation") -> Assessment:
        if kind == "scenario" and (self._environment != "sim" or not platform.startswith("sim-")):
            raise AssessmentError("en scenariobedömning finns bara i simuleringens egen databas (D-058)")
        digest = params_hash(initiative_data, platform_data)
        params = {"initiative": initiative_data, "platform": platform_data}
        with self._db.transaction() as tx:
            assessment_id = tx.execute(
                "INSERT INTO assessments (kind, initiative, platform, params_hash, params, result, ready, actor, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, initiative, platform, digest, json.dumps(params, ensure_ascii=False, sort_keys=True),
                 json.dumps(result, ensure_ascii=False, sort_keys=True), int(ready), actor, self._clock()),
            ).lastrowid
        self._audit.append(actor, "assessment.recorded", {"assessment_id": assessment_id, "initiative": initiative,
                                                          "platform": platform, "ready": ready, "kind": kind})
        return self.get(assessment_id)

    def approve(self, founder: str, assessment_id: int, note: str) -> Assessment:
        a = self._require(assessment_id)
        if founder not in self._founders:
            raise AssessmentError("bara en grundare godkänner en bedömning (D-049, D-058)")
        if not a.ready:
            raise AssessmentError("bedömningen är inte redo: initiativet klarar inte kraven (D-048, D-058)")
        return self._decide(founder, a, "approved", note)

    def reject(self, founder: str, assessment_id: int, note: str) -> Assessment:
        a = self._require(assessment_id)
        if founder not in self._founders:
            raise AssessmentError("bara en grundare beslutar om en bedömning (D-049)")
        if not note.strip():
            raise AssessmentError("ett nej kräver en motivering")
        return self._decide(founder, a, "rejected", note)

    def get(self, assessment_id: int) -> Assessment | None:
        row = self._db.connection.execute(
            "SELECT assessment_id, kind, initiative, platform, params_hash, params, result, ready, actor, at "
            "FROM assessments WHERE assessment_id = ?", (assessment_id,)).fetchone()
        if row is None:
            return None
        event = self._db.connection.execute(
            "SELECT event, actor FROM assessment_events WHERE assessment_id = ?", (assessment_id,)).fetchone()
        aid, kind, init, plat, digest, params, result, ready, actor, at = row
        return Assessment(aid, kind, init, plat, digest, json.loads(params), json.loads(result), bool(ready), actor,
                          at, event[0] if event else None, event[1] if event else None)

    def for_initiative(self, initiative: str) -> tuple[Assessment, ...]:
        ids = [r[0] for r in self._db.connection.execute(
            "SELECT assessment_id FROM assessments WHERE initiative = ? ORDER BY assessment_id", (initiative,))]
        return tuple(self.get(i) for i in ids)

    def valid(self, initiative: str, initiative_data: dict, platform_data: dict) -> Assessment | None:
        """Den senaste godkända och redo bedömningen med exakt de här parametrarna, eller None."""
        digest = params_hash(initiative_data, platform_data)
        for a in reversed(self.for_initiative(initiative)):
            if a.decision == "approved" and a.ready and a.params_hash == digest:
                return a
        return None

    def valid_for_platform(self, platform: str, platform_data: dict, initiatives) -> Assessment | None:
        """En giltig bedömning för något initiativ på plattformen. `initiatives`: (nyckel, data)."""
        for key, data in initiatives:
            if data.get("platform") == platform:
                a = self.valid(key, data, platform_data)
                if a is not None:
                    return a
        return None

    def _require(self, assessment_id: int) -> Assessment:
        a = self.get(assessment_id)
        if a is None:
            raise AssessmentError(f"bedömning {assessment_id} finns inte")
        return a

    def _decide(self, founder: str, a: Assessment, event: str, note: str) -> Assessment:
        try:
            with self._db.transaction() as tx:
                tx.execute("INSERT INTO assessment_events (assessment_id, event, actor, note, at) VALUES (?, ?, ?, ?, ?)",
                           (a.assessment_id, event, founder, note, self._clock()))
        except sqlite3.IntegrityError:
            raise AssessmentError(f"bedömning {a.assessment_id} har redan ett beslut") from None
        self._audit.append(founder, f"assessment.{event}", {"assessment_id": a.assessment_id, "note": note})
        return self.get(a.assessment_id)


def check_active(register, ledger, incidents, today: str, pause_after_days: int, currency: str = "SIM") -> list[str]:
    """PR 6, D-058: ett aktivt initiativ som har legat under den pessimistiska prognosen i `pause_after_days`
    dagar pausas av systemet och får en incident. Returnerar de initiativ som pausades.

    Prognosen är det pessimistiska scenariots median av nettot per dag i den godkända bedömningen. Utfallet
    är initiativets netto i ledgern (intäkter − återbetalningar − avgifter − kostnader) de senaste dagarna.
    Ett initiativ som har varit aktivt kortare tid än så prövas inte än.
    """
    from datetime import date, timedelta

    from ..ledger import compute_result
    from .registry import SYSTEM

    paused = []
    end = date.fromisoformat(today)
    start = (end - timedelta(days=pause_after_days - 1)).isoformat()
    for entry in register.all("initiative", "active"):
        platform = register.get("platform", entry.data.get("platform", ""))
        a = register.assessments.valid(entry.key, entry.data, platform.data) if platform else None
        forecast = (a.result.get("scenarios", {}).get("pessimistic", {}) if a else {}).get("daily_net_minor")
        if forecast is None:
            continue
        activated = next((v.at[:10] for v in reversed(register.history("initiative", entry.key))
                          if v.status == "active"), None)
        if activated is None or activated > start:
            continue  # inte aktivt länge nog
        window = tuple(e for e in ledger.entries(currency) if e.initiative == entry.key and start <= e.recorded_at[:10] <= today)
        actual = compute_result(window, currency).net_minor
        expected = forecast * pause_after_days
        if actual >= expected:
            continue
        reason = (f"under den pessimistiska prognosen i {pause_after_days} dagar: netto {actual} mot minst "
                  f"{expected} ({start} – {today}, bedömning {a.assessment_id})")
        register.set_status(SYSTEM, "initiative", entry.key, "paused", reason)
        if incidents is not None:
            incidents.open("system:incidents", f"Initiativet {entry.key} pausades automatiskt",
                           f"autopause:{entry.key}:{today}", department=entry.data.get("department", "research"),
                           actions=f"pausat automatiskt (D-058): {reason}", follow_up_owner="founders")
        paused.append(entry.key)
    return paused
