"""Avstängning och avveckling bara på dokumenterade kriterier (Fas 5f, SR-17, konstitutionen §31–§33, D-040).

En verksam agent (ACTIVE, PROBATION eller SUSPENDED) kan bara stängas av eller avvecklas genom ett
**ärende**. När `RemovalReview` är kopplad (`AgentRegistry.set_guard`) blockerar registret alla andra vägar.

Ett ärende anger:
- **kriterier** ur §33: `exceeded_authority`, `repeated_rule_breaches`, `false_reports`,
  `critical_quality`, `unacceptable_costs` eller `security_risk`
- **underlag** för varje kriterium, som kontrolleras:

| Underlag | Krav |
|---|---|
| `incident:<id>` | verifierad incident (alla 16 fält) där agenten är **involverad**; att ha rapporterat räknas inte |
| `audit:<seq>` | `tool.denied` i revisionsloggen för agenten med ett verktyg **utanför** rollens mandat |
| `review:<id>` | en sparad prestationsbedömning av agenten (5c) |
| `ledger:<id>` | en ledgerpost (kostnader) |

**Slutsatser är aldrig underlag** (SR-17). Rapporter, beslut, samråd, tvister och lärdomar
(`report:`, `decision:`, `dispute:`, `lesson:`) avvisas. En agent kan alltså inte stängas av för
vad den kom fram till, bara för vad den gjorde. Kriterier med ordet *upprepade* (`repeated_rule_breaches`)
kräver minst två underlag.

Proportionalitet (§33): avstängning beslutas av en grundare och avveckling av båda. Agenten kan
lämna ett yttrande (`respond`), och ett ärende kan avskrivas. Ingen kan öppna ett ärende om sig själv,
och den som öppnar ett ärende kan inte själv besluta om det, om den inte är grundare och den andra
grundaren också röstar (avveckling). Allt sparas append-only (migration 25) och loggas.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..agents import ACTING_STATES, LEVEL_HEAD, AgentRegistry, AgentState
from ..audit import AuditLog
from ..memory import Database

SYSTEM = "system:removal"
CRITERIA = {
    "exceeded_authority": "Överskrider sin behörighet",
    "repeated_rule_breaches": "Bryter upprepade gånger mot operativa regler",
    "false_reports": "Producerar systematiskt felaktiga rapporter",
    "critical_quality": "Misslyckas med kritiska kvalitetskrav",
    "unacceptable_costs": "Genererar oacceptabla kostnader",
    "security_risk": "Utgör en säkerhetsrisk",
}
REPEATED = frozenset({"repeated_rule_breaches", "false_reports"})
CONCLUSIONS = ("report:", "decision:", "dispute:", "lesson:", "consultation:")
TARGETS = {"SUSPENDED": AgentState.SUSPENDED, "RETIRED": AgentState.RETIRED}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RemovalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CaseEvent:
    event: str
    actor: str
    note: str
    at: str


@dataclass(frozen=True, slots=True)
class RemovalCase:
    case_id: int
    agent_id: str
    target: str
    criteria: dict[str, list[str]]  # kriterium → underlag
    note: str
    opened_by: str
    at: str
    events: tuple[CaseEvent, ...] = ()

    @property
    def status(self) -> str:
        kinds = [e.event for e in self.events]
        for final in ("executed", "dismissed", "approved"):
            if final in kinds:
                return final
        return "open"

    @property
    def votes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(e.actor for e in self.events if e.event == "vote"))

    @property
    def response(self) -> str | None:
        return next((e.note for e in reversed(self.events) if e.event == "response"), None)


class RemovalReview:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions,
        audit: AuditLog,
        founders: frozenset[str],
        incidents,
        performance=None,
        ledger=None,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._incident_log = incidents
        self._performance = performance
        self._ledger = ledger
        self._clock = clock
        registry.set_guard(self)

    # --- Ärenden ---------------------------------------------------------------------------

    def open(self, actor: str, agent_id: str, target: str, criteria: dict[str, tuple[str, ...]], note: str) -> RemovalCase:
        if actor == agent_id:
            raise RemovalError("ingen öppnar ett ärende om sig själv")
        self._require_opener(actor)
        agent = self._registry.get(agent_id)
        if agent is None:
            raise RemovalError(f"agenten {agent_id!r} finns inte")
        if target not in TARGETS:
            raise RemovalError("målet är SUSPENDED (avstängning) eller RETIRED (avveckling)")
        if not note.strip():
            raise RemovalError("beskriv ärendet")
        if not criteria:
            raise RemovalError(f"ange minst ett kriterium ur §33 ({', '.join(CRITERIA)}); SR-17")
        for criterion, evidence in criteria.items():
            self._check(agent, criterion, tuple(evidence))
        if any(c.agent_id == agent_id and c.status in ("open", "approved") for c in self.cases()):
            raise RemovalError(f"det finns redan ett öppet ärende om {agent_id}")
        payload = {k: list(v) for k, v in criteria.items()}
        with self._db.transaction() as tx:
            case_id = tx.execute(
                "INSERT INTO removal_cases (agent_id, target, criteria, evidence, note, opened_by, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (agent_id, target, json.dumps(sorted(payload)), json.dumps(payload), note, actor, self._clock()),
            ).lastrowid
        self._audit.append(actor, "removal.opened", {"case_id": case_id, "agent_id": agent_id, "target": target,
                                                     "criteria": payload, "notify": ["founders", agent_id]})
        return self.get(case_id)

    def respond(self, agent_id: str, case_id: int, text: str) -> RemovalCase:
        """Agentens eget yttrande. Får lämnas även när agenten är avstängd."""
        case = self._require(case_id)
        if agent_id != case.agent_id:
            raise RemovalError("bara agenten som ärendet gäller yttrar sig")
        if not text.strip():
            raise RemovalError("yttrandet är tomt")
        self._event(case, "response", agent_id, text)
        return self.get(case_id)

    def vote(self, founder: str, case_id: int, note: str) -> RemovalCase:
        """Grundarnas beslut: avstängning kräver en grundare, avveckling båda. Genomförs direkt (§33)."""
        case = self._require(case_id)
        if founder not in self._founders:
            raise RemovalError("bara grundarna beslutar om avstängning och avveckling (§33, SR-17)")
        if case.status != "open":
            raise RemovalError(f"ärendet är {case.status}")
        if founder in case.votes:
            raise RemovalError(f"{founder} har redan röstat")
        if not note.strip():
            raise RemovalError("motivera beslutet")
        if case.target == "SUSPENDED" and founder == case.opened_by:
            raise RemovalError("den som öppnade ärendet beslutar inte ensam om det; den andra grundaren beslutar")
        self._event(case, "vote", founder, note)
        votes = set(self.get(case_id).votes)
        needed = {founder} if case.target == "SUSPENDED" else self._founders
        if votes >= needed:
            self._event(case, "approved", founder, f"beslutat av {', '.join(sorted(votes))}")
            self._execute(self.get(case_id))
        return self.get(case_id)

    def dismiss(self, founder: str, case_id: int, note: str) -> RemovalCase:
        case = self._require(case_id)
        if founder not in self._founders:
            raise RemovalError("bara grundarna avskriver ärenden")
        if case.status != "open":
            raise RemovalError(f"ärendet är {case.status}")
        if not note.strip():
            raise RemovalError("motivera avskrivningen")
        self._event(case, "dismissed", founder, note)
        return self.get(case_id)

    # --- Spärren i registret ---------------------------------------------------------------

    def transition_block_reason(self, agent_id: str, old: AgentState, new: AgentState, changed_by: str) -> str | None:
        if changed_by == SYSTEM and self._approved(agent_id, new.value) is not None:
            return None
        return (f"{agent_id} kan bara bli {new.value} genom ett beslutat ärende med dokumenterade kriterier "
                "(SR-17, §33); använd RemovalReview")

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, case_id: int) -> RemovalCase | None:
        row = self._db.connection.execute(
            "SELECT case_id, agent_id, target, evidence, note, opened_by, at FROM removal_cases WHERE case_id = ?",
            (case_id,)).fetchone()
        if row is None:
            return None
        events = tuple(CaseEvent(*r) for r in self._db.connection.execute(
            "SELECT event, actor, note, at FROM removal_events WHERE case_id = ? ORDER BY id", (case_id,)))
        cid, agent_id, target, evidence, note, opened_by, at = row
        return RemovalCase(cid, agent_id, target, json.loads(evidence), note, opened_by, at, events)

    def cases(self, agent_id: str | None = None) -> tuple[RemovalCase, ...]:
        ids = [r[0] for r in self._db.connection.execute("SELECT case_id FROM removal_cases ORDER BY case_id")]
        cases = tuple(self.get(i) for i in ids)
        return cases if agent_id is None else tuple(c for c in cases if c.agent_id == agent_id)

    # --- Internt ---------------------------------------------------------------------------

    def _check(self, agent, criterion: str, evidence: tuple[str, ...]) -> None:
        if criterion not in CRITERIA:
            raise RemovalError(f"{criterion!r} är inget kriterium i §33 ({', '.join(CRITERIA)}); SR-17")
        if not evidence:
            raise RemovalError(f"{criterion}: underlag krävs (SR-17)")
        if criterion in REPEATED and len(set(evidence)) < 2:
            raise RemovalError(f"{criterion} gäller upprepade fel och kräver minst två underlag")
        for ref in evidence:
            if not isinstance(ref, str):
                raise RemovalError(f"ogiltigt underlag {ref!r}")
            if ref.startswith(CONCLUSIONS):
                raise RemovalError(f"{ref}: slutsatser är aldrig underlag för avstängning (SR-17)")
            kind, _, value = ref.partition(":")
            if not value.isdigit():
                raise RemovalError(f"{ref}: använd incident:, audit:, review: eller ledger: med ett nummer")
            n = int(value)
            if kind == "incident":
                incident = self._incident_log.get(n)
                if incident is None or agent.agent_id not in incident.involved:
                    raise RemovalError(f"{ref}: agenten är inte involverad (att rapportera ett fel räknas aldrig, §31)")
                if not incident.complete:
                    raise RemovalError(f"{ref}: incidenten är inte verifierad än")
            elif kind == "audit":
                entry = next((e for e in self._audit.entries() if e.seq == n), None)
                tools = self._permissions.roles[agent.role].tools
                if (entry is None or entry.action != "tool.denied" or entry.details.get("agent_id") != agent.agent_id
                        or entry.details.get("tool") in tools):
                    raise RemovalError(f"{ref}: inget försök utanför mandatet av {agent.agent_id}")
            elif kind == "review":
                if self._performance is None or not any(r.review_id == n for r in self._performance.reviews(agent.agent_id)):
                    raise RemovalError(f"{ref}: ingen sparad bedömning av {agent.agent_id}")
            elif kind == "ledger":
                if self._ledger is None or self._ledger.get(n) is None:
                    raise RemovalError(f"{ref}: ledgerposten finns inte")
            else:
                raise RemovalError(f"{ref}: okänd typ av underlag")

    def _execute(self, case: RemovalCase) -> None:
        agent = self._registry.get(case.agent_id)
        target = TARGETS[case.target]
        if agent.state is not target:
            self._registry.transition(case.agent_id, target, SYSTEM,
                                      f"ärende {case.case_id} ({', '.join(case.criteria)}): {case.note}")
        self._event(case, "executed", SYSTEM, f"{case.agent_id} är {case.target}")

    def _approved(self, agent_id: str, target: str) -> RemovalCase | None:
        return next((c for c in self.cases(agent_id) if c.target == target and c.status == "approved"), None)

    def _require(self, case_id: int) -> RemovalCase:
        case = self.get(case_id)
        if case is None:
            raise RemovalError(f"ärende {case_id} finns inte")
        return case

    def _require_opener(self, actor: str) -> None:
        if actor in self._founders:
            return
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise RemovalError(f"{actor!r} finns inte eller får inte agera just nu")
        if self._permissions.roles[agent.role].level > LEVEL_HEAD:
            raise RemovalError("ärenden öppnas av grundarna eller nivå 1–3")

    def _event(self, case: RemovalCase, event: str, actor: str, note: str) -> None:
        with self._db.transaction() as tx:
            tx.execute("INSERT INTO removal_events (case_id, event, actor, note, at) VALUES (?, ?, ?, ?, ?)",
                       (case.case_id, event, actor, note, self._clock()))
        self._audit.append(actor, f"removal.{event}", {"case_id": case.case_id, "agent_id": case.agent_id,
                                                       "target": case.target, "note": note})
