"""Hela systemet ihopkopplat (Fas 6a, D-041). `python -m aie start` bygger det här.

`build_system()` kopplar ihop alla komponenter med spärrar och loggar, i den här ordningen:

| Komponent | Kopplas till |
|---|---|
| `KillSwitch` (SR-07) | `AuthorizationEngine` och `BudgetEngine`; skapar incidenter |
| `ProtectedMode` (SR-08) | `AuthorizationEngine` och `BudgetEngine`; aktiverar nödstoppet; skapar incidenter |
| `ControlStops` (§8 nivå 2) | `AuthorizationEngine` |
| `TaxEngine` (ER-18–21) | `AuthorizationEngine` (momsgränsen) och `BudgetEngine` (reserverad skatt) |
| `StopLoss` (ER-13) | `BudgetEngine`; skapar incidenter |
| `IncidentLog`, `ForecastLog`, `LessonRegistry`, `StrategyRegistry`, `PerformanceReview` | Fas 5 |
| `RemovalReview` (SR-17) | `AgentRegistry.set_guard`: avstängning bara genom ärende |

Saknas en konfigurationsfil, eller går något inte att bygga, startar systemet inte. Det startar
aldrig utan sina spärrar (§59).

`System.tick()` körs i varje varv av körloopen:
1. `StopLoss.evaluate()`, men först när kapital finns i ledgern (D-027 punkt 1). Före det är
   ingenting disponibelt, så budgetmotorn blockerar ändå alla utgifter.
2. `IncidentLog.sync()`: stopp som saknar incident får en.
3. `TaxEngine.check_vat()`: varning och gräns loggas en gång per år.
4. `ForecastLog.evaluate()`: förfallna prognoser jämförs med ledgern.

Skyddat driftläge bedöms före varje utgift (spärren i budgetmotorn), inte i loopen. Ett fel i en
kontroll loggas och gör att `tick()` rapporterar felet. Loopen fortsätter, och spärrarna gäller fortfarande.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .agents import AgentRegistry
from .audit import AuditLog
from .authorization import AuthorizationEngine, ControlStops, load_permissions
from .budget import BudgetEngine, load_budgets
from .config import Config
from .evaluation import (ForecastLog, IncidentLog, LessonRegistry, PerformanceReview, RemovalReview,
                         StrategyRegistry)
from .ledger import EntryType, Ledger, Status
from .memory import Database
from .monitoring import get_logger
from .orchestration import TaskBoard
from .risk import KillSwitch, ProtectedMode, StopLoss
from .risk.protected import COMPONENT as PROTECTED_MODE
from .tax import TaxEngine, load_tax_config

log = get_logger("system")


@dataclass
class System:
    audit: AuditLog
    registry: AgentRegistry
    engine: AuthorizationEngine
    ledger: Ledger
    budget: BudgetEngine
    kill: KillSwitch
    protected: ProtectedMode
    stoploss: StopLoss
    tax: TaxEngine
    tasks: TaskBoard
    incidents: IncidentLog
    forecasts: ForecastLog
    lessons: LessonRegistry
    strategies: StrategyRegistry
    performance: PerformanceReview
    removal: RemovalReview
    currency: str = "SIM"
    errors: list[str] = field(default_factory=list)

    @property
    def components(self) -> tuple[str, ...]:
        return ("kill_switch", "protected_mode", "control_stops", "tax", "stoploss", "incidents", "forecasts",
                "lessons", "strategies", "performance", "removal_guard")

    def tick(self) -> list[str]:
        """Kör de återkommande kontrollerna. Returnerar felen, som också loggas."""
        errors: list[str] = []
        checks = (("stoploss", self._stoploss), ("incidents", self.incidents.sync),
                  ("vat", self.tax.check_vat), ("forecasts", self.forecasts.evaluate))
        for name, check in checks:
            try:
                check()
            except Exception as exc:  # noqa: BLE001 — en kontroll som kraschar får inte stoppa de andra
                message = f"kontrollen {name} kunde inte genomföras ({type(exc).__name__}: {exc})"
                log.error(message)
                errors.append(message)
        self.errors = errors
        return errors

    def _stoploss(self) -> None:
        capitalised = any(e.entry_type is EntryType.CAPITAL_IN and e.status is Status.SETTLED
                          for e in self.ledger.entries(self.currency))
        if capitalised:
            self.stoploss.evaluate()


def build_system(config: Config, db: Database, config_dir: Path | str) -> System:
    """Bygger hela systemet. Kastar `ConfigError` om en konfigurationsfil saknas eller är fel."""
    founders = frozenset(config.system.founders)
    limits = config.risk
    permissions = load_permissions(config_dir)
    departments = {m.department for m in permissions.roles.values()}
    budgets = load_budgets(config_dir, departments, limits)
    tax_config = load_tax_config(config_dir, founders)

    audit = AuditLog(db)
    registry = AgentRegistry(permissions, db)
    incidents = IncidentLog(db, registry, permissions, audit, founders)
    kill = KillSwitch(db, registry, permissions, audit, founders, components=frozenset({PROTECTED_MODE}),
                      incidents=incidents)
    stops = ControlStops(db, registry, permissions, audit, founders)
    engine = AuthorizationEngine(permissions, registry, config.system.environment, audit, stops=stops, gates=(kill,))
    threshold = limits.human_approval_threshold.amount_minor if limits.human_approval_threshold else None
    ledger = Ledger(db, engine, departments, founders, audit, threshold)
    tax = TaxEngine(db, ledger, tax_config, audit, founders, engine)
    engine.add_gate(tax)
    protected = ProtectedMode(db, ledger, registry, permissions, limits, engine, audit, founders, kill_switch=kill,
                              incidents=incidents)
    engine.add_gate(protected)
    stoploss = StopLoss(db, ledger, limits, budgets, audit, founders, incidents=incidents)
    budget = BudgetEngine(ledger, limits, budgets, audit, gates=(stoploss, kill, protected), tax=tax)
    tasks = TaskBoard(db, registry, engine, founders=founders)
    forecasts = ForecastLog(db, registry, permissions, audit, founders, ledger)
    lessons = LessonRegistry(db, registry, permissions, audit, founders, incidents, forecasts)
    strategies = StrategyRegistry(db, registry, permissions, audit, founders, lessons)
    performance = PerformanceReview(db, registry, permissions, audit, founders, incidents, forecasts, tasks, ledger,
                                    currency=limits.currency)
    removal = RemovalReview(db, registry, permissions, audit, founders, incidents, performance, ledger)
    system = System(audit, registry, engine, ledger, budget, kill, protected, stoploss, tax, tasks, incidents,
                    forecasts, lessons, strategies, performance, removal, limits.currency)
    return system
