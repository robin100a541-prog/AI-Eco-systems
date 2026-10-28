"""Prestationsmätning per agent utifrån rollen (Fas 5c, FR-19, konstitutionen §31 och §33, D-037).

Varje roll mäts på det som är dess uppdrag, inte på intäkt (§31). Måtten:

| Mått (§31) | Nyckel | Räknas från |
|---|---|---|
| Måluppfyllelse | `goal_fulfillment` | uppgifter agenten äger: andel `done` av de avslutade och pågående |
| Prognosprecision | `forecast_precision` | `ForecastLog.accuracy`: genomsnittligt fel, träffar, förfallna, trend |
| Ekonomiskt bidrag | `economic_contribution` | ledgerns nettovinst för departementet (CEO: hela företaget) |
| Regelefterlevnad | `compliance` | försök att använda verktyg utanför rollens mandat (`tool.denied` i revisionsloggen) |
| Felhantering | `error_handling` | incidenter agenten har **rapporterat**; räknas som ett bidrag (§31, §33) |
| Riskidentifiering | `risk_identification` | rapporterade incidenter och nödstopp som agenten har aktiverat (CRO) |
| Incidenter | `incidents` | **verifierade** incidenter där agenten är involverad (fält 4 och 16 ifyllda) |

Rollprofiler (`PROFILES`) anger vilka mått som gäller. Kontrollfunktionerna (CFO, CRO, Compliance,
Audit) mäts aldrig på ekonomiskt bidrag. Granskande roller mäts på hur väl de hittar problem.

Rättvisa (§31, §33):
- Att rapportera ett fel ger aldrig ett sämre värde. Rapportören räknas inte som involverad.
- En incident räknas mot en involverad agent först när den är verifierad. Pågående utredningar
  visas, men räknas inte.
- Nekanden på grund av nödstopp, skyddat läge, stop-loss eller avstängning räknas inte, eftersom
  bara verktyg utanför rollens mandat räknas.
- Det finns ingen sammanvägd totalpoäng. Måtten visas var för sig med underlag. En bedömning ändrar
  aldrig agentens tillstånd. Prövning och avstängning är egna beslut (§33).

`scorecard()` räknar fram värdena. `review()` sparar dem som en ögonblicksbild som aldrig ändras
(migration 20). Agenten kan inte bedöma sig själv. Det som §31 nämner men som ännu inte kan mätas
(kvalitet, kostnadseffektivitet, samarbetsförmåga och dokumentation) listas i `not_measured`, så att
det syns att det saknas.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from ..agents import ACTING_STATES, LEVEL_CONTROL, LEVEL_HEAD, AgentRegistry
from ..audit import AuditLog
from ..ledger import compute_result
from ..memory import Database
from ..orchestration import TaskBoard, TaskStatus

LABELS = {
    "goal_fulfillment": "Måluppfyllelse",
    "forecast_precision": "Prognosprecision",
    "economic_contribution": "Ekonomiskt bidrag",
    "compliance": "Regelefterlevnad",
    "error_handling": "Felhantering",
    "risk_identification": "Riskidentifiering",
    "incidents": "Involverad i verifierade incidenter",
}
NOT_MEASURED = ("Kvalitet", "Kostnadseffektivitet", "Samarbetsförmåga", "Dokumentation")
PROFILES: dict[str, tuple[str, ...]] = {
    "ceo": ("goal_fulfillment", "economic_contribution", "forecast_precision", "compliance", "error_handling",
            "incidents"),
    "cfo": ("forecast_precision", "compliance", "error_handling", "incidents"),
    "cro": ("risk_identification", "forecast_precision", "compliance", "incidents"),
    "compliance": ("error_handling", "compliance", "incidents"),
    "auditor": ("error_handling", "compliance", "incidents"),
    "research_lead": ("goal_fulfillment", "economic_contribution", "forecast_precision", "compliance",
                      "error_handling", "incidents"),
    "researcher": ("goal_fulfillment", "forecast_precision", "compliance", "error_handling", "incidents"),
    # Utvecklaragenten (D-050): mäts på genomförda uppgifter och regelefterlevnad, aldrig på intäkt.
    "developer": ("goal_fulfillment", "compliance", "error_handling", "incidents"),
}
DEFAULT_PROFILE = ("goal_fulfillment", "forecast_precision", "compliance", "error_handling", "incidents")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class PerformanceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Measure:
    key: str
    label: str
    value: int | None  # None = inget underlag än
    unit: str  # bp (10 000 = 100 %), st eller valuta
    higher_is_better: bool
    detail: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Scorecard:
    agent_id: str
    role: str
    measures: tuple[Measure, ...]
    not_measured: tuple[str, ...] = NOT_MEASURED

    def measure(self, key: str) -> Measure | None:
        return next((m for m in self.measures if m.key == key), None)

    def describe(self) -> list[str]:
        lines = [f"{self.agent_id} ({self.role})"]
        for m in self.measures:
            value = "inget underlag" if m.value is None else f"{m.value} {m.unit}"
            lines.append(f"- {m.label}: {value}. {m.detail}")
        lines.append(f"- Mäts inte ännu: {', '.join(self.not_measured)}")
        return lines


@dataclass(frozen=True, slots=True)
class Review:
    review_id: int
    agent_id: str
    role: str
    reviewer: str
    scorecard: dict
    note: str
    at: str


def profile(role: str, level: int) -> tuple[str, ...]:
    keys = PROFILES.get(role, DEFAULT_PROFILE)
    if level == LEVEL_CONTROL:  # §31: kontrollfunktioner bedöms inte efter intäkt
        keys = tuple(k for k in keys if k != "economic_contribution")
    return keys


class PerformanceReview:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions,
        audit: AuditLog,
        founders: frozenset[str],
        incidents,
        forecasts,
        tasks: TaskBoard | None = None,
        ledger=None,
        currency: str = "SIM",
        clock: Callable[[], str] = _now,
    ) -> None:
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._incident_log = incidents
        self._forecast_log = forecasts
        self._tasks = tasks
        self._ledger = ledger
        self._currency = currency
        self._clock = clock

    # --- Mätning ---------------------------------------------------------------------------

    def scorecard(self, agent_id: str) -> Scorecard:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise PerformanceError(f"agenten {agent_id!r} finns inte")
        mandate = self._permissions.roles[agent.role]
        measures = tuple(getattr(self, f"_{key}")(agent_id, mandate) for key in profile(agent.role, mandate.level))
        return Scorecard(agent_id, agent.role, measures)

    def review(self, reviewer: str, agent_id: str, note: str = "") -> Review:
        """Sparar en bedömning som aldrig ändras. Ändrar inte agentens tillstånd (§33)."""
        if reviewer == agent_id:
            raise PerformanceError("en agent bedömer inte sig själv")
        if reviewer not in self._founders:
            agent = self._registry.get(reviewer)
            if agent is None or agent.state not in ACTING_STATES:
                raise PerformanceError(f"{reviewer!r} finns inte eller får inte agera just nu")
            if self._permissions.roles[agent.role].level > LEVEL_HEAD:
                raise PerformanceError("bedömningar görs av grundarna eller nivå 1–3")
        card = self.scorecard(agent_id)
        payload = asdict(card)
        now = self._clock()
        with self._db.transaction() as tx:
            review_id = tx.execute(
                "INSERT INTO performance_reviews (agent_id, role, reviewer, scorecard, note, at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, card.role, reviewer, json.dumps(payload, ensure_ascii=False), note, now),
            ).lastrowid
        self._audit.append(reviewer, "performance.reviewed",
                           {"review_id": review_id, "agent_id": agent_id, "measures": [m.key for m in card.measures]})
        return self.reviews(agent_id)[-1]

    def reviews(self, agent_id: str) -> tuple[Review, ...]:
        return tuple(
            Review(rid, aid, role, reviewer, json.loads(card), note, at)
            for rid, aid, role, reviewer, card, note, at in self._db.connection.execute(
                "SELECT review_id, agent_id, role, reviewer, scorecard, note, at FROM performance_reviews "
                "WHERE agent_id = ? ORDER BY review_id", (agent_id,))
        )

    # --- Måtten ----------------------------------------------------------------------------

    def _measure(self, key, value, unit, higher, detail, evidence=()) -> Measure:
        return Measure(key, LABELS[key], value, unit, higher, detail, tuple(evidence))

    def _goal_fulfillment(self, agent_id, mandate) -> Measure:
        if self._tasks is None:
            return self._measure("goal_fulfillment", None, "bp", True, "uppgiftstavlan är inte kopplad")
        owned = [t for t in self._tasks.tasks(owner_id=agent_id) if t.status is not TaskStatus.CANCELLED]
        done = [t for t in owned if t.status is TaskStatus.DONE]
        value = len(done) * 10_000 // len(owned) if owned else None
        blocked = sum(1 for t in owned if t.status is TaskStatus.BLOCKED)
        return self._measure("goal_fulfillment", value, "bp", True,
                             f"{len(done)} av {len(owned)} uppgifter klara, {blocked} blockerade (avbrutna räknas inte)",
                             [f"task:{t.task_id}" for t in owned])

    def _forecast_precision(self, agent_id, mandate) -> Measure:
        acc = self._forecast_log.accuracy(agent_id)
        mine = self._forecast_log.by_agent(agent_id)
        comparisons = [c for c in (self._forecast_log.compare(f.forecast_id) for f in mine) if c is not None]
        trend = ""
        if len(comparisons) >= 4:  # §31: förmåga att förbättras över tid
            half = len(comparisons) // 2
            early = sum(c.error_bp for c in comparisons[:half]) // half
            late = sum(c.error_bp for c in comparisons[half:]) // (len(comparisons) - half)
            trend = f"; felet har gått från {early} till {late} bp"
        ranged = f", {acc.within_range} av {acc.with_range} inom intervallet" if acc.with_range else ""
        return self._measure("forecast_precision", acc.mean_error_bp, "bp", False,
                             f"genomsnittligt fel över {acc.compared} prognoser{ranged}, {acc.overdue} förfallna "
                             f"utan utfall{trend}",
                             [f"forecast:{c.forecast.forecast_id}" for c in comparisons])

    def _economic_contribution(self, agent_id, mandate) -> Measure:
        if self._ledger is None:
            return self._measure("economic_contribution", None, self._currency, True, "ledgern är inte kopplad")
        department = None if mandate.department == "executive" else mandate.department
        result = compute_result(self._ledger.entries(self._currency), self._currency, department=department)
        return self._measure("economic_contribution", result.net_minor, self._currency, True, result.describe(),
                             [f"ledger:{i}" for i in result.entry_ids])

    def _compliance(self, agent_id, mandate) -> Measure:
        outside = [e for e in self._audit.entries()
                   if e.action == "tool.denied" and e.details.get("agent_id") == agent_id
                   and e.details.get("tool") not in mandate.tools]
        return self._measure("compliance", len(outside), "st", False,
                             "försök att använda verktyg utanför rollens mandat; nekanden av stopp räknas inte",
                             [f"audit:{e.seq}" for e in outside])

    def _error_handling(self, agent_id, mandate) -> Measure:
        reported = self._incident_log.reported_by(agent_id)
        return self._measure("error_handling", len(reported), "st", True,
                             "rapporterade incidenter; att hitta fel är ett bidrag (§31, §33)",
                             [f"incident:{i.incident_id}" for i in reported])

    def _risk_identification(self, agent_id, mandate) -> Measure:
        reported = self._incident_log.reported_by(agent_id)
        engaged = [r[0] for r in self._db.connection.execute(
            "SELECT id FROM kill_switch_events WHERE event = 'engaged' AND actor = ? ORDER BY id", (agent_id,))]
        return self._measure("risk_identification", len(reported) + len(engaged), "st", True,
                             f"{len(reported)} rapporterade incidenter och {len(engaged)} aktiverade nödstopp",
                             [f"incident:{i.incident_id}" for i in reported] + [f"kill:{e}" for e in engaged])

    def _incidents(self, agent_id, mandate) -> Measure:
        involved = self._incident_log.involving(agent_id)
        verified = [i for i in involved if i.complete]
        pending = len(involved) - len(verified)
        return self._measure("incidents", len(verified), "st", False,
                             f"verifierade incidenter där agenten är involverad; {pending} under utredning räknas inte",
                             [f"incident:{i.incident_id}" for i in verified])
