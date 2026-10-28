"""Lärdomsregister med verifieringsstatus (Fas 5d, FR-17, konstitutionen §27, §29 och §30, D-038).

En lärdom har ett påstående, en orsakstyp enligt §29, ett område och minst en källa: `incident:<id>`,
`forecast:<id>`, `decision:<id>`, `task:<id>`, `ledger:<id>` eller `test:<namn>`. Statusen går ett
steg i taget:

| Status (§29) | Nyckel | Krav för att nå den |
|---|---|---|
| Obekräftad hypotes | `hypothesis` | föreslagen med källa |
| Preliminär lärdom | `preliminary` | granskad av grundare eller nivå 1–3, inte av den som föreslog |
| Testad lärdom | `tested` | minst ett test: en prognos med utfall eller ett `test:`-underlag |
| Reproducerbart resultat | `reproducible` | minst två olika test |
| Godkänd operativ regel | `operational_rule` | **båda** grundarna röstar för (§29, §53) |

Regler:
- **En obekräftad hypotes blir aldrig automatiskt en regel** (§53). Inget steg kan hoppas över, och
  sista steget kräver en grundare (D-049).
- **Bara godkända operativa regler får ändra gemensamma regler.** `require_rule()` kastar för allt annat.
  Strategiversionerna (FR-18) använder den när en ändring sägs vara obligatorisk.
- En lärdom kan sänkas (`demote`) eller avvisas (`reject`) med motivering, till exempel när nytt
  underlag talar emot den. Inget raderas eller skrivs om (migration 23), så historiken finns kvar.
- Alla aktiva agenter kan föreslå en lärdom. `from_incident()` skapar en från en incidents grundorsak.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..agents import ACTING_STATES, LEVEL_HEAD, AgentRegistry
from ..audit import AuditLog
from ..memory import Database

STATUSES = ("hypothesis", "preliminary", "tested", "reproducible", "operational_rule")
LABELS = {
    "hypothesis": "Obekräftad hypotes",
    "preliminary": "Preliminär lärdom",
    "tested": "Testad lärdom",
    "reproducible": "Reproducerbart resultat",
    "operational_rule": "Godkänd operativ regel",
    "rejected": "Avvisad",
}
CAUSES = {
    "random": "Slumpmässigt utfall",
    "predictable_error": "Förutsägbart fel",
    "bad_information": "Felaktig information",
    "bad_execution": "Felaktigt genomförande",
    "bad_strategy": "Felaktig strategi",
    "market_change": "Förändrade marknadsförhållanden",
    "insufficient_data": "Otillräckligt testunderlag",
}
_SOURCE = re.compile(r"(incident|forecast|decision|task|ledger|test):\S+")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class LessonError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LessonEvent:
    event: str
    status: str | None
    actor: str
    note: str
    evidence: tuple[str, ...]
    at: str


@dataclass(frozen=True, slots=True)
class Lesson:
    lesson_id: int
    statement: str
    cause: str
    scope: str
    sources: tuple[str, ...]
    proposed_by: str
    at: str
    events: tuple[LessonEvent, ...] = ()

    @property
    def status(self) -> str:
        status = "hypothesis"
        for e in self.events:
            if e.status is not None and e.event in ("promote", "demote", "reject"):
                status = e.status
        return status

    @property
    def tests(self) -> tuple[str, ...]:
        """Olika testunderlag: prognoser och test:-poster bland källor och tillagt underlag."""
        all_evidence = [*self.sources, *(x for e in self.events if e.event == "evidence" for x in e.evidence)]
        return tuple(dict.fromkeys(x for x in all_evidence if x.startswith(("forecast:", "test:"))))

    @property
    def rule_votes(self) -> tuple[str, ...]:
        """Grundare som har röstat för regel sedan lärdomen senast ändrade status."""
        votes: list[str] = []
        for e in self.events:
            if e.event in ("promote", "demote", "reject"):
                votes = []
            elif e.event == "rule_vote":
                votes.append(e.actor)
        return tuple(dict.fromkeys(votes))


class LessonRegistry:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions,
        audit: AuditLog,
        founders: frozenset[str],
        incidents=None,
        forecasts=None,
        clock: Callable[[], str] = _now,
    ) -> None:
        """`incidents`/`forecasts`: loggarna som källorna kontrolleras mot, om de är kopplade."""
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._incidents = incidents
        self._forecasts = forecasts
        self._clock = clock

    # --- Föreslå ---------------------------------------------------------------------------

    def propose(self, actor: str, statement: str, cause: str, scope: str, sources: tuple[str, ...]) -> Lesson:
        self._require_acting(actor)
        if not statement.strip():
            raise LessonError("en lärdom behöver ett påstående")
        if cause not in CAUSES:
            raise LessonError(f"okänd orsak {cause!r} (§29: {', '.join(CAUSES)})")
        if not scope.strip():
            raise LessonError("ange område, till exempel ett departement eller company")
        self._check_sources(sources, need=1)
        with self._db.transaction() as tx:
            lesson_id = tx.execute(
                "INSERT INTO lessons (statement, cause, scope, sources, proposed_by, at) VALUES (?, ?, ?, ?, ?, ?)",
                (statement, cause, scope, json.dumps(list(sources)), actor, self._clock()),
            ).lastrowid
        self._audit.append(actor, "lesson.proposed", {"lesson_id": lesson_id, "cause": cause, "sources": list(sources)})
        return self.get(lesson_id)

    def from_incident(self, actor: str, incident_id: int, cause: str, statement: str | None = None) -> Lesson:
        """En hypotes från en incidents grundorsak (§27: vad hände, varför)."""
        if self._incidents is None:
            raise LessonError("incidentloggen är inte kopplad")
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise LessonError(f"incident {incident_id} finns inte")
        fields = incident.fields
        text = statement or fields.get("preventive") or fields.get("root_cause")
        if not text:
            raise LessonError("incidenten saknar grundorsak och förebyggande åtgärd; ange ett påstående")
        return self.propose(actor, text, cause, fields.get("department", "company"), (f"incident:{incident_id}",))

    # --- Verifiera -------------------------------------------------------------------------

    def add_evidence(self, actor: str, lesson_id: int, evidence: tuple[str, ...], note: str) -> Lesson:
        lesson = self._require(lesson_id)
        self._require_acting(actor)
        self._check_sources(evidence, need=1)
        if not note.strip():
            raise LessonError("beskriv vad underlaget visar")
        self._event(lesson, "evidence", None, actor, note, evidence)
        return self.get(lesson_id)

    def promote(self, actor: str, lesson_id: int, note: str) -> Lesson:
        """Höjer statusen ett steg. Sista steget kräver en grundare (`vote_rule`, D-049)."""
        lesson = self._require(lesson_id)
        self._require_reviewer(actor, lesson)
        if not note.strip():
            raise LessonError("motivera höjningen")
        if lesson.status == "rejected":
            raise LessonError("en avvisad lärdom höjs inte; föreslå en ny")
        target = self._next(lesson)
        if target == "operational_rule":
            raise LessonError("en operativ regel kräver en grundares röst (vote_rule, §29, D-049)")
        if target == "tested" and not lesson.tests:
            raise LessonError("en testad lärdom kräver ett test: en prognos med utfall eller ett test:-underlag")
        if target == "reproducible" and len(lesson.tests) < 2:
            raise LessonError(f"ett reproducerbart resultat kräver minst två olika test (har {len(lesson.tests)})")
        self._event(lesson, "promote", target, actor, note, ())
        return self.get(lesson_id)

    def vote_rule(self, founder: str, lesson_id: int, note: str) -> Lesson:
        """En grundares röst för att göra ett reproducerbart resultat till en operativ regel."""
        lesson = self._require(lesson_id)
        if founder not in self._founders:
            raise LessonError("bara grundarna gör en lärdom till en operativ regel (§29, §53)")
        if lesson.status != "reproducible":
            raise LessonError(f"bara reproducerbara resultat kan bli regler; status är {LABELS[lesson.status]}")
        if founder in lesson.rule_votes:
            raise LessonError(f"{founder} har redan röstat; den andra grundaren måste också rösta")
        if not note.strip():
            raise LessonError("motivera rösten")
        self._event(lesson, "rule_vote", None, founder, note, ())
        if self.get(lesson_id).rule_votes:  # D-049: en grundares röst räcker
            self._event(lesson, "promote", "operational_rule", founder, "en grundare har godkänt regeln (D-049)", ())
        return self.get(lesson_id)

    def demote(self, actor: str, lesson_id: int, status: str, note: str, evidence: tuple[str, ...] = ()) -> Lesson:
        lesson = self._require(lesson_id)
        self._require_reviewer(actor, lesson, allow_proposer=True)
        if status not in STATUSES or STATUSES.index(status) >= STATUSES.index(self._current(lesson)):
            raise LessonError("en sänkning går till en lägre status")
        if not note.strip():
            raise LessonError("motivera sänkningen")
        if evidence:
            self._check_sources(evidence, need=1)
        self._event(lesson, "demote", status, actor, note, evidence)
        return self.get(lesson_id)

    def reject(self, actor: str, lesson_id: int, note: str) -> Lesson:
        lesson = self._require(lesson_id)
        self._require_reviewer(actor, lesson, allow_proposer=True)
        if not note.strip():
            raise LessonError("motivera varför lärdomen avvisas")
        self._event(lesson, "reject", "rejected", actor, note, ())
        return self.get(lesson_id)

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, lesson_id: int) -> Lesson | None:
        row = self._db.connection.execute(
            "SELECT lesson_id, statement, cause, scope, sources, proposed_by, at FROM lessons WHERE lesson_id = ?",
            (lesson_id,)).fetchone()
        if row is None:
            return None
        events = tuple(
            LessonEvent(event, status, actor, note, tuple(json.loads(evidence)), at)
            for event, status, actor, note, evidence, at in self._db.connection.execute(
                "SELECT event, status, actor, note, evidence, at FROM lesson_events WHERE lesson_id = ? ORDER BY id",
                (lesson_id,))
        )
        lid, statement, cause, scope, sources, proposed_by, at = row
        return Lesson(lid, statement, cause, scope, tuple(json.loads(sources)), proposed_by, at, events)

    def all(self, status: str | None = None) -> tuple[Lesson, ...]:
        ids = [r[0] for r in self._db.connection.execute("SELECT lesson_id FROM lessons ORDER BY lesson_id")]
        lessons = tuple(self.get(i) for i in ids)
        return lessons if status is None else tuple(x for x in lessons if x.status == status)

    def rules(self) -> tuple[Lesson, ...]:
        """De enda lärdomar som får ändra gemensamma operativa regler (§29)."""
        return self.all("operational_rule")

    def require_rule(self, lesson_id: int) -> Lesson:
        lesson = self._require(lesson_id)
        if lesson.status != "operational_rule":
            raise LessonError(f"lärdom {lesson_id} är {LABELS[lesson.status]}, inte en godkänd operativ regel; "
                              "den får inte ändra gemensamma regler (FR-17, §53)")
        return lesson

    # --- Internt ---------------------------------------------------------------------------

    def _current(self, lesson: Lesson) -> str:
        return lesson.status if lesson.status != "rejected" else STATUSES[-1]

    @staticmethod
    def _next(lesson: Lesson) -> str:
        i = STATUSES.index(lesson.status)
        if i == len(STATUSES) - 1:
            raise LessonError("lärdomen är redan en operativ regel")
        return STATUSES[i + 1]

    def _check_sources(self, sources, need: int) -> None:
        if not isinstance(sources, (list, tuple)) or len(sources) < need:
            raise LessonError("en lärdom behöver minst en källa (§30: tidsstämpel, källa, historik)")
        bad = [s for s in sources if not isinstance(s, str) or not _SOURCE.fullmatch(s)]
        if bad:
            raise LessonError(f"ogiltiga källor {bad}; använd incident:, forecast:, decision:, task:, ledger: eller test:")
        for s in sources:
            kind, _, ref = s.partition(":")
            if kind == "incident" and self._incidents is not None:
                if not ref.isdigit() or self._incidents.get(int(ref)) is None:
                    raise LessonError(f"{s} finns inte")
            if kind == "forecast" and self._forecasts is not None:
                forecast = self._forecasts.get(int(ref)) if ref.isdigit() else None
                if forecast is None or forecast.outcome is None:
                    raise LessonError(f"{s} finns inte eller saknar utfall; en prognos är ett test först när utfallet finns")

    def _require(self, lesson_id: int) -> Lesson:
        lesson = self.get(lesson_id)
        if lesson is None:
            raise LessonError(f"lärdom {lesson_id} finns inte")
        return lesson

    def _require_acting(self, actor: str):
        if actor in self._founders:
            return None
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise LessonError(f"{actor!r} finns inte eller får inte agera just nu")
        return agent

    def _require_reviewer(self, actor: str, lesson: Lesson, allow_proposer: bool = False) -> None:
        agent = self._require_acting(actor)
        if not allow_proposer and actor == lesson.proposed_by:
            raise LessonError("den som föreslog lärdomen granskar den inte själv")
        if agent is not None and self._permissions.roles[agent.role].level > LEVEL_HEAD:
            raise LessonError("lärdomar granskas av grundarna eller nivå 1–3")

    def _event(self, lesson: Lesson, event, status, actor, note, evidence) -> None:
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO lesson_events (lesson_id, event, status, actor, note, evidence, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (lesson.lesson_id, event, status, actor, note, json.dumps(list(evidence)), self._clock()),
            )
        self._audit.append(actor, f"lesson.{event}", {"lesson_id": lesson.lesson_id, "status": status, "note": note})
