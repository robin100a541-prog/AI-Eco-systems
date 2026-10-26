"""Stop-loss (Fas 4e-1, ER-13, konstitutionen §26, D-029).

> När en budgetgräns, reservgräns eller maximal tillåten förlust nås ska den berörda
> verksamheten automatiskt stoppas eller begränsas.

`StopLoss.evaluate()` mäter fyra gränser direkt från ledgern (ER-09, ER-16) och sparar en
**utlösning** för varje gräns som har nåtts (migration 15):

| Gräns | Omfattning | Utlöses när |
|---|---|---|
| `MAX_SINGLE_EXPERIMENT_LOSS` | ett initiativ | den realiserade nettoförlusten (settled) ≥ gränsen |
| `MAX_TOTAL_DRAWDOWN` | hela företaget | (START_CAPITAL − likvida medel) / START_CAPITAL ≥ gränsen i procent |
| departementets `budget` | ett departement | utgifterna (väntade och genomförda) ≥ budgeten |
| `MINIMUM_RESERVE` | hela företaget | likvida medel − åtaganden ≤ reserven, så att inget längre kan disponeras |

En gräns som saknas räknas som nådd (ER-02: saknad gräns betyder blockera).

Vid en utlösning gör systemet det som §26 kräver:
- **Blockerar nya åtaganden** i det berörda området. `StopLoss` är en spärr som `BudgetEngine`
  frågar före varje utgift (`gates=`).
- **Beräknar exponeringen:** väntade utbetalningar i området och deras poster.
- **Identifierar befintliga förpliktelser** (samma väntade poster). De **hanteras och ignoreras inte**:
  stop-lossen avbryter eller raderar inga poster. De betalas eller avbryts som vanligt via ledgern.
- **Informerar** riskfunktionen (CRO), CFO och, för ett departement, dess departementschef.
  Det loggas i revisionsloggen.
- **Kräver nytt godkännande** innan verksamheten återupptas. Två olika grundare måste godkänna
  en återhämtningsplan (D-019 punkt 3, eftersom det gäller riskgränserna). Det går inte medan
  gränsen fortfarande är nådd. Då måste läget åtgärdas först, eller gränsen ändras via PR.

Inget raderas. Utlösningar och godkännanden är append-only och revideras.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..audit import AuditLog
from ..budget.capital import capital_position
from ..budget.config import Budget
from ..config.models import RiskLimits
from ..ledger import EntryType, Ledger, Status, compute_result
from ..memory import Database

COMPONENT = "system:stoploss"
_SPEND = frozenset({EntryType.COST, EntryType.FEE})
_OUT = frozenset({EntryType.COST, EntryType.FEE, EntryType.REFUND, EntryType.CAPITAL_OUT})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StopLossError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Breach:
    scope_kind: str  # company, department eller initiative
    scope_value: str
    limit_name: str
    measured: str  # som text, så att procent och belopp kan sparas exakt
    limit_value: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.scope_kind, self.scope_value, self.limit_name)


@dataclass(frozen=True, slots=True)
class Trip:
    trip_id: int
    scope_kind: str
    scope_value: str
    limit_name: str
    measured: str
    limit_value: str
    currency: str
    exposure: dict
    notified: tuple[str, ...]
    tripped_at: str
    approvals: tuple[str, ...] = ()  # grundare som har godkänt återhämtningsplanen

    @property
    def active(self) -> bool:
        return len(set(self.approvals)) < 2

    def describe(self) -> str:
        return (f"stop-loss #{self.trip_id}: {self.limit_name} nådd för {self.scope_kind} {self.scope_value} "
                f"({self.measured} ≥ {self.limit_value}) (ER-13)")


class StopLoss:
    def __init__(
        self,
        db: Database,
        ledger: Ledger,
        limits: RiskLimits,
        budgets: dict[str, Budget],
        audit: AuditLog,
        founders: frozenset[str],
        notify: Callable[[str, str], tuple[str, ...]] | None = None,
        clock: Callable[[], str] = _now,
        incidents=None,
    ) -> None:
        """`notify(scope_kind, scope_value)` returnerar vilka som ska informeras. Standard: roller.

        `incidents`: en `IncidentLog`; varje ny utlösning blir då en incident (FR-15, Fas 5a).
        """
        self._db = db
        self._ledger = ledger
        self._limits = limits
        self._budgets = dict(budgets)
        self._audit = audit
        self._founders = frozenset(founders)
        self._notify = notify or _default_recipients
        self._clock = clock
        self._incident_log = incidents

    # --- Mätning -------------------------------------------------------------------------

    def breaches(self) -> tuple[Breach, ...]:
        """Alla gränser som är nådda just nu. Ren läsning; inget sparas."""
        limits, currency = self._limits, self._limits.currency
        entries = self._ledger.entries(currency)
        out: list[Breach] = []

        loss_limit = limits.max_single_experiment_loss
        for initiative in sorted({e.initiative for e in entries}):
            net = compute_result(entries, currency, initiative=initiative).net_minor
            if net >= 0:
                continue
            if loss_limit is None:
                out.append(Breach("initiative", initiative, "MAX_SINGLE_EXPERIMENT_LOSS", str(-net), "saknas"))
            elif -net >= loss_limit.amount_minor:
                out.append(Breach("initiative", initiative, "MAX_SINGLE_EXPERIMENT_LOSS", str(-net),
                                  str(loss_limit.amount_minor)))

        position = capital_position(entries, limits)
        start, drawdown_limit = limits.start_capital, limits.max_total_drawdown
        if start is None or drawdown_limit is None or start.amount_minor <= 0:
            out.append(Breach("company", "*", "MAX_TOTAL_DRAWDOWN", "okänd", "saknas"))
        else:
            loss = max(0, start.amount_minor - position.liquid_minor)
            percent = Decimal(loss) * 100 / Decimal(start.amount_minor)
            if percent >= drawdown_limit:
                out.append(Breach("company", "*", "MAX_TOTAL_DRAWDOWN", f"{percent:.2f}%", f"{drawdown_limit}%"))

        if position.reserve_minor is None:
            out.append(Breach("company", "*", "MINIMUM_RESERVE", "okänd", "saknas"))
        elif position.liquid_minor - position.committed_minor <= position.reserve_minor:
            out.append(Breach("company", "*", "MINIMUM_RESERVE",
                              str(position.liquid_minor - position.committed_minor), str(position.reserve_minor)))

        for department, budget in sorted(self._budgets.items()):
            spent = sum(e.amount_minor for e in entries if e.department == department
                        and e.entry_type in _SPEND and e.status in (Status.PENDING, Status.SETTLED))
            if spent >= budget.budget_minor:
                out.append(Breach("department", department, "budget", str(spent), str(budget.budget_minor)))
        return tuple(out)

    def evaluate(self) -> tuple[Trip, ...]:
        """Sparar en utlösning för varje nådd gräns som inte redan har en aktiv. Returnerar de nya."""
        active = {(t.scope_kind, t.scope_value, t.limit_name) for t in self.active()}
        new: list[Trip] = []
        for breach in self.breaches():
            if breach.key in active:
                continue
            exposure = self._exposure(breach)
            notified = self._notify(breach.scope_kind, breach.scope_value)
            now = self._clock()
            with self._db.transaction() as tx:
                cursor = tx.execute(
                    "INSERT INTO stop_loss_trips (scope_kind, scope_value, limit_name, measured, limit_value, "
                    "currency, exposure, notified, tripped_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (breach.scope_kind, breach.scope_value, breach.limit_name, breach.measured, breach.limit_value,
                     self._limits.currency, json.dumps(exposure), json.dumps(list(notified)), now),
                )
            trip = Trip(cursor.lastrowid, *breach.key[:2], breach.limit_name, breach.measured, breach.limit_value,
                        self._limits.currency, exposure, tuple(notified), now)
            self._audit.append(COMPONENT, "stoploss.tripped", {
                "trip_id": trip.trip_id, "scope_kind": trip.scope_kind, "scope_value": trip.scope_value,
                "limit": trip.limit_name, "measured": trip.measured, "limit_value": trip.limit_value,
                "exposure_minor": exposure["pending_outflow_minor"], "obligations": exposure["pending_entry_ids"],
                "notified": list(notified),
            })
            new.append(trip)
            active.add(breach.key)
        if new and self._incident_log is not None:
            self._incident_log.sync()
        return tuple(new)

    # --- Återupptagande ------------------------------------------------------------------

    def approve_resume(self, founder: str, trip_id: int, plan: str) -> Trip:
        """En grundares godkännande av återhämtningsplanen. Två olika grundare krävs (D-029)."""
        if founder not in self._founders:
            raise StopLossError("bara grundarna kan återuppta efter en stop-loss (ER-13, D-019 punkt 3)")
        if not plan.strip():
            raise StopLossError("en återhämtningsplan krävs (§26)")
        trip = self.get(trip_id)
        if trip is None or not trip.active:
            raise StopLossError(f"stop-loss #{trip_id} finns inte eller är redan återupptagen")
        if founder in trip.approvals:
            raise StopLossError(f"{founder} har redan godkänt; den andra grundaren måste också godkänna")
        if any(b.key == (trip.scope_kind, trip.scope_value, trip.limit_name) for b in self.breaches()):
            raise StopLossError(
                f"{trip.limit_name} är fortfarande nådd för {trip.scope_kind} {trip.scope_value}; "
                "åtgärda läget eller ändra gränsen via PR (D-019 punkt 3) innan verksamheten återupptas"
            )
        with self._db.transaction() as tx:
            tx.execute("INSERT INTO stop_loss_votes (trip_id, founder, plan, at) VALUES (?, ?, ?, ?)",
                       (trip_id, founder, plan, self._clock()))
        trip = self.get(trip_id)
        self._audit.append(founder, "stoploss.resume_approved" if not trip.active else "stoploss.resume_vote",
                           {"trip_id": trip_id, "approvals": list(trip.approvals), "resumed": not trip.active})
        return trip

    # --- Spärr för BudgetEngine ----------------------------------------------------------

    def spend_block_reasons(self, request) -> list[str]:
        """Skäl att stoppa en ny utgift. Anropas av BudgetEngine före varje utgift."""
        reasons = []
        for trip in self.active():
            hit = (trip.scope_kind == "company"
                   or (trip.scope_kind == "department" and trip.scope_value == request.department)
                   or (trip.scope_kind == "initiative" and trip.scope_value == request.initiative))
            if hit:
                reasons.append(trip.describe() + "; nya åtaganden blockeras tills två grundare godkänt en plan")
        return reasons

    # --- Frågor --------------------------------------------------------------------------

    def get(self, trip_id: int) -> Trip | None:
        row = self._db.connection.execute(_SELECT + " WHERE trip_id = ?", (trip_id,)).fetchone()
        return None if row is None else self._trip(row)

    def active(self) -> tuple[Trip, ...]:
        trips = (self._trip(r) for r in self._db.connection.execute(_SELECT + " ORDER BY trip_id"))
        return tuple(t for t in trips if t.active)

    def _trip(self, row) -> Trip:
        trip_id, kind, value, name, measured, limit, currency, exposure, notified, at = row
        approvals = tuple(f for (f,) in self._db.connection.execute(
            "SELECT founder FROM stop_loss_votes WHERE trip_id = ? ORDER BY id", (trip_id,)))
        return Trip(trip_id, kind, value, name, measured, limit, currency, json.loads(exposure),
                    tuple(json.loads(notified)), at, approvals)

    def _exposure(self, breach: Breach) -> dict:
        """Väntade utbetalningar i området: exponering och förpliktelser som måste hanteras."""
        pending = [
            e for e in self._ledger.entries(self._limits.currency)
            if e.status is Status.PENDING and e.entry_type in _OUT and (
                breach.scope_kind == "company"
                or (breach.scope_kind == "department" and e.department == breach.scope_value)
                or (breach.scope_kind == "initiative" and e.initiative == breach.scope_value))
        ]
        return {
            "pending_outflow_minor": sum(e.amount_minor for e in pending),
            "pending_entry_ids": [e.entry_id for e in pending],
        }


def _default_recipients(scope_kind: str, scope_value: str) -> tuple[str, ...]:
    recipients = ["role:cro", "role:cfo"]
    if scope_kind == "department":
        recipients.append(f"head:{scope_value}")
    return tuple(recipients)


_SELECT = (
    "SELECT trip_id, scope_kind, scope_value, limit_name, measured, limit_value, currency, exposure, notified, "
    "tripped_at FROM stop_loss_trips"
)
