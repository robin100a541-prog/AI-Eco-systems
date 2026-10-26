"""Prognoslogg och prognos mot utfall (Fas 5b, FR-16, konstitutionen §20 steg 10, D-036).

En prognos sparas **innan** utfallet finns:

| Fält | Betydelse |
|---|---|
| `agent` | vem som gjorde prognosen |
| `subject` | vad prognosen gäller, i klartext |
| `metric` | `net`, `revenue` eller `costs` (räknas från ledgern) eller `count` (rapporteras) |
| `unit` | valuta för ledgermåtten (D-006), annars till exempel `st` |
| `expected`, `low`, `high` | väntat värde och ett valfritt intervall, heltal i minsta enhet |
| `initiative` | ledgerns affärsinitiativ, krävs för ledgermåtten |
| `decision` | valfri länk till beslutet, `decision:<id>` |
| `due` | datum då utfallet ska finnas (ÅÅÅÅ-MM-DD) |

Måtten från ledgern (ER-09): `net` är nettovinsten, `revenue` är intäkter minus återbetalningar
och `costs` är kostnader plus avgifter.

Regler:
- **Inget raderas eller skrivs om** (migration 19). En ny bedömning görs med `revise()` och blir en ny
  prognos som pekar på den gamla. Den gamla finns kvar och jämförs också, eftersom §20 steg 10
  jämför med den *ursprungliga* prognosen. Ingen kan revidera efter förfallodagen.
- **Automatisk jämförelse:** `evaluate()` hämtar utfallet från ledgern för förfallna prognoser med
  ledgermått. Resultatet används bara när det inte är preliminärt (ER-11). Underlaget, det vill säga
  vilka ledgerposter som räknades, sparas med utfallet. `overdue()` visar förfallna prognoser
  som fortfarande saknar utfall.
- **Rapporterat utfall** (`count`) registreras av grundarna eller agenter på nivå 1–3, men aldrig av
  den som gjorde prognosen.
- **Rättelser** av utfall är nya poster med motivering som pekar på det gamla utfallet.
- `accuracy(agent)` sammanfattar träffsäkerheten. Den används av prestationsmätningen (5c, §31).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from ..agents import ACTING_STATES, LEVEL_HEAD, AgentRegistry
from ..audit import AuditLog
from ..ledger import compute_result
from ..memory import Database

SYSTEM = "system:forecasts"
LEDGER_METRICS = frozenset({"net", "revenue", "costs"})
METRICS = LEDGER_METRICS | {"count"}
_DECISION = re.compile(r"decision:\S+")
_CURRENCY = re.compile(r"[A-Z]{3}")
_COLUMNS = "forecast_id, agent, subject, metric, unit, expected, low, high, initiative, decision, due, revises, made_at"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ForecastError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Outcome:
    outcome_id: int
    actual: int
    source: str  # ledger | manual
    evidence: tuple[str, ...]
    note: str
    actor: str
    corrects: int | None
    at: str


@dataclass(frozen=True, slots=True)
class Forecast:
    forecast_id: int
    agent: str
    subject: str
    metric: str
    unit: str
    expected: int
    low: int | None
    high: int | None
    initiative: str | None
    decision: str | None
    due: str
    revises: int | None
    made_at: str
    outcomes: tuple[Outcome, ...] = ()

    @property
    def outcome(self) -> Outcome | None:
        """Det gällande utfallet: den senaste posten, så att rättelser gäller."""
        return self.outcomes[-1] if self.outcomes else None


@dataclass(frozen=True, slots=True)
class Comparison:
    forecast: Forecast
    actual: int
    deviation: int  # utfall − prognos
    error_bp: int  # |avvikelse| i baspunkter av |prognos| (10 000 = 100 %)
    within_range: bool | None  # None när prognosen saknar intervall

    def describe(self) -> str:
        f = self.forecast
        rng = "" if self.within_range is None else (" inom intervallet" if self.within_range else " utanför intervallet")
        return (f"Prognos {f.forecast_id} ({f.subject}): väntat {f.expected} {f.unit}, utfall {self.actual} {f.unit}, "
                f"avvikelse {self.deviation:+d} ({self.error_bp / 100:.1f} %){rng}")


@dataclass(frozen=True, slots=True)
class Accuracy:
    agent: str
    compared: int
    within_range: int
    with_range: int
    mean_error_bp: int | None
    overdue: int


class ForecastLog:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions,
        audit: AuditLog,
        founders: frozenset[str],
        ledger=None,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._ledger = ledger
        self._clock = clock

    # --- Prognoser -------------------------------------------------------------------------

    def make(
        self,
        agent: str,
        subject: str,
        metric: str,
        unit: str,
        expected: int,
        due: str,
        low: int | None = None,
        high: int | None = None,
        initiative: str | None = None,
        decision: str | None = None,
        revises: int | None = None,
    ) -> Forecast:
        self._require_acting(agent)
        problems = self._validate(subject, metric, unit, expected, due, low, high, initiative, decision)
        if problems:
            raise ForecastError("; ".join(problems))
        due = date.fromisoformat(due).isoformat()
        now = self._clock()
        if due < now[:10]:
            raise ForecastError(f"förfallodagen {due} har redan passerat; en prognos görs innan utfallet finns")
        with self._db.transaction() as tx:
            forecast_id = tx.execute(
                f"INSERT INTO forecasts ({_COLUMNS.split(', ', 1)[1]}) VALUES ({', '.join('?' * 12)})",
                (agent, subject, metric, unit, expected, low, high, initiative, decision, due, revises, now),
            ).lastrowid
        self._audit.append(agent, "forecast.revised" if revises else "forecast.made",
                           {"forecast_id": forecast_id, "subject": subject, "metric": metric, "expected": expected,
                            "unit": unit, "due": due, "revises": revises})
        return self.get(forecast_id)

    def revise(self, agent: str, forecast_id: int, expected: int, low: int | None = None, high: int | None = None,
               due: str | None = None) -> Forecast:
        """En ny bedömning. Den gamla prognosen finns kvar och jämförs också (§20 steg 10)."""
        old = self._require(forecast_id)
        if agent != old.agent and agent not in self._founders:
            raise ForecastError("bara den som gjorde prognosen, eller en grundare, reviderar den")
        if old.outcome is not None or old.due < self._clock()[:10]:
            raise ForecastError("en prognos kan inte revideras efter förfallodagen eller när utfallet finns")
        if self._revision_of(forecast_id) is not None:
            raise ForecastError(f"prognos {forecast_id} är redan reviderad; revidera den senaste")
        return self.make(agent, old.subject, old.metric, old.unit, expected, due or old.due, low, high,
                         old.initiative, old.decision, revises=forecast_id)

    # --- Utfall ----------------------------------------------------------------------------

    def record_outcome(self, actor: str, forecast_id: int, actual: int, note: str = "",
                       evidence: tuple[str, ...] = ()) -> Forecast:
        """Rapporterat utfall för `count`. Finns ett utfall redan blir det en rättelse med motivering."""
        forecast = self._require(forecast_id)
        self._require_assessor(actor, forecast)
        if not isinstance(actual, int) or isinstance(actual, bool):
            raise ForecastError("utfallet ska vara ett heltal")
        if forecast.metric in LEDGER_METRICS and forecast.outcome is None:
            raise ForecastError("ledgermått hämtas från ledgern med evaluate(); rapportera bara en rättelse")
        previous = forecast.outcome
        if previous is not None and not note.strip():
            raise ForecastError("utfallet finns redan; en rättelse kräver en motivering")
        self._insert(forecast_id, actual, "manual", evidence, note, actor, previous.outcome_id if previous else None)
        return self.get(forecast_id)

    def evaluate(self) -> tuple[Comparison, ...]:
        """Hämtar utfall från ledgern för förfallna prognoser som saknar utfall. Säkert att anropa ofta."""
        if self._ledger is None:
            return ()
        today = self._clock()[:10]
        done: list[Comparison] = []
        for forecast in self.all():
            if forecast.metric not in LEDGER_METRICS or forecast.outcome is not None or forecast.due > today:
                continue
            result = compute_result(self._ledger.entries(forecast.unit), forecast.unit, initiative=forecast.initiative)
            if result.preliminary:
                continue  # ER-11: ett preliminärt resultat är inget utfall
            actual = {"net": result.net_minor,
                      "revenue": result.revenue_minor - result.refunds_minor,
                      "costs": result.costs_minor + result.fees_minor}[forecast.metric]
            evidence = tuple(f"ledger:{i}" for i in result.entry_ids)
            self._insert(forecast.forecast_id, actual, "ledger", evidence, result.describe(), SYSTEM, None)
            done.append(self.compare(forecast.forecast_id))
        return tuple(done)

    # --- Jämförelse ------------------------------------------------------------------------

    def compare(self, forecast_id: int) -> Comparison | None:
        forecast = self._require(forecast_id)
        if forecast.outcome is None:
            return None
        actual = forecast.outcome.actual
        deviation = actual - forecast.expected
        error_bp = abs(deviation) * 10_000 // max(abs(forecast.expected), 1)
        within = None
        if forecast.low is not None or forecast.high is not None:
            within = (forecast.low is None or actual >= forecast.low) and (forecast.high is None or actual <= forecast.high)
        return Comparison(forecast, actual, deviation, error_bp, within)

    def overdue(self) -> tuple[Forecast, ...]:
        today = self._clock()[:10]
        return tuple(f for f in self.all() if f.outcome is None and f.due < today)

    def accuracy(self, agent: str) -> Accuracy:
        mine = self.by_agent(agent)
        comparisons = [c for c in (self.compare(f.forecast_id) for f in mine) if c is not None]
        ranged = [c for c in comparisons if c.within_range is not None]
        mean = sum(c.error_bp for c in comparisons) // len(comparisons) if comparisons else None
        today = self._clock()[:10]
        return Accuracy(agent, len(comparisons), sum(1 for c in ranged if c.within_range), len(ranged), mean,
                        sum(1 for f in mine if f.outcome is None and f.due < today))

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, forecast_id: int) -> Forecast | None:
        row = self._db.connection.execute(f"SELECT {_COLUMNS} FROM forecasts WHERE forecast_id = ?",
                                          (forecast_id,)).fetchone()
        if row is None:
            return None
        outcomes = tuple(
            Outcome(oid, actual, source, tuple(json.loads(evidence)), note, actor, corrects, at)
            for oid, actual, source, evidence, note, actor, corrects, at in self._db.connection.execute(
                "SELECT id, actual, source, evidence, note, actor, corrects, at FROM forecast_outcomes "
                "WHERE forecast_id = ? ORDER BY id", (forecast_id,))
        )
        return Forecast(*row, outcomes=outcomes)

    def all(self) -> tuple[Forecast, ...]:
        ids = [r[0] for r in self._db.connection.execute("SELECT forecast_id FROM forecasts ORDER BY forecast_id")]
        return tuple(self.get(i) for i in ids)

    def by_agent(self, agent: str) -> tuple[Forecast, ...]:
        return tuple(f for f in self.all() if f.agent == agent)

    # --- Internt ---------------------------------------------------------------------------

    def _insert(self, forecast_id, actual, source, evidence, note, actor, corrects) -> None:
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO forecast_outcomes (forecast_id, actual, source, evidence, note, actor, corrects, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (forecast_id, actual, source, json.dumps(list(evidence)), note, actor, corrects, self._clock()),
            )
        self._audit.append(actor, "forecast.outcome_corrected" if corrects else "forecast.outcome",
                           {"forecast_id": forecast_id, "actual": actual, "source": source, "note": note})

    def _revision_of(self, forecast_id: int) -> int | None:
        row = self._db.connection.execute("SELECT forecast_id FROM forecasts WHERE revises = ?",
                                          (forecast_id,)).fetchone()
        return row[0] if row else None

    def _require(self, forecast_id: int) -> Forecast:
        forecast = self.get(forecast_id)
        if forecast is None:
            raise ForecastError(f"prognos {forecast_id} finns inte")
        return forecast

    def _require_acting(self, actor: str):
        if actor in self._founders:
            return None
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise ForecastError(f"{actor!r} finns inte eller får inte agera just nu")
        return agent

    def _require_assessor(self, actor: str, forecast: Forecast) -> None:
        if actor == forecast.agent:
            raise ForecastError("den som gjorde prognosen rapporterar inte själv utfallet")
        agent = self._require_acting(actor)
        if agent is not None and self._permissions.roles[agent.role].level > LEVEL_HEAD:
            raise ForecastError("utfall rapporteras av grundarna eller nivå 1–3")

    @staticmethod
    def _validate(subject, metric, unit, expected, due, low, high, initiative, decision) -> list[str]:
        problems: list[str] = []
        if not isinstance(subject, str) or not subject.strip():
            problems.append("ange vad prognosen gäller")
        if metric not in METRICS:
            problems.append(f"okänt mått {metric!r} (tillåtna: {', '.join(sorted(METRICS))})")
        for name, value in (("expected", expected), ("low", low), ("high", high)):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                problems.append(f"{name} ska vara ett heltal i minsta enhet (D-006)")
        if isinstance(expected, int) and isinstance(low, int) and low > expected:
            problems.append("low är större än expected")
        if isinstance(expected, int) and isinstance(high, int) and high < expected:
            problems.append("high är mindre än expected")
        if metric in LEDGER_METRICS:
            if not isinstance(unit, str) or not _CURRENCY.fullmatch(unit):
                problems.append("ledgermått har en valuta som enhet, till exempel SIM")
            if not initiative:
                problems.append("ledgermått kräver ett affärsinitiativ")
        elif not isinstance(unit, str) or not unit.strip():
            problems.append("ange en enhet")
        try:
            date.fromisoformat(due)
        except (TypeError, ValueError):
            problems.append("due ska vara ett datum, ÅÅÅÅ-MM-DD")
        if decision is not None and not _DECISION.fullmatch(decision):
            problems.append("decision ska vara decision:<id>")
        return problems
