"""Är affärsmodellen lönsam nog för riktiga pengar? (Fas 6b, D-048, §54, §55)

`evaluate()` kör samma scenario många gånger med olika seed, var och en i en egen tillfällig databas,
och med samma agenter och spärrar som vanligt. Sedan bedöms körningarna tillsammans. **Ett lyckat
utfall räcker aldrig.** Kraven står i `config/simulation.toml` under `[readiness]`:

| Krav | Nyckel |
|---|---|
| Antal oberoende körningar (olika seed) | `min_runs` |
| Simulerade dagar per körning | `min_days` |
| Varje körning har positivt resultat efter alla kostnader, avgifter och reserverad skatt | — |
| Varje körning har positivt resultat även de sista `recent_days` dagarna (hållbart, inte en tidig topp) | `recent_days` |
| Medianmarginalen efter skatt är minst `min_margin_percent` av intäkterna | `min_margin_percent` |
| Ingen körning löste ut stop-loss för hela företaget, skyddat driftläge eller nödstopp | — |
| Det lägsta likvida kapitalet föll aldrig under `max_drawdown_percent` från startkapitalet | `max_drawdown_percent` |

Resultatet är en **rekommendation**, aldrig en handling:
- **Inte redo:** skälen listas, och systemet fortsätter i simuleringen.
- **Redo för en första riktig investering** på `first_real_investment` (500 kr), men först efter grundarnas
  uttryckliga godkännande (D-019) och med Fas 7:s villkor uppfyllda (§55, Q-03–Q-05, Q-07). Inget i
  simuleringen kan sätta in eller flytta riktiga pengar. Ledgern avvisar `SIM` i prod och tvärtom (ER-15).
- **Att öka** till `next_real_investment` (1 000 kr) bedöms först på resultat från riktiga pengar, inte
  på simuleringen.

Rapporten sparas som JSON i `<data_dir>/reports/` med SHA-256 och kan granskas i efterhand (§30).
"""
from __future__ import annotations

import hashlib
import json
import statistics
import tempfile
import tomllib
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..config import ConfigError
from ..ledger import EntryType, Status, compute_result
from ..memory import Database
from .agents import agent_data_class, build_gateway, ensure_org
from .cycle import WorkCycle
from .market import SimClock
from .run import Simulation, require_sim
from .scenario import Scenario

SIMULATION_FILE = "simulation.toml"
_READINESS_KEYS = ("min_runs", "min_days", "recent_days", "min_margin_percent", "max_drawdown_percent",
                   "first_real_investment", "next_real_investment")


@dataclass(frozen=True, slots=True)
class ReadinessRules:
    min_runs: int
    min_days: int
    recent_days: int
    min_margin_percent: int
    max_drawdown_percent: int
    first_real_investment: int
    next_real_investment: int


@dataclass(frozen=True, slots=True)
class RunResult:
    seed: str
    days: int
    revenue_minor: int  # intäkter minus återbetalningar
    fees_minor: int
    costs_minor: int
    net_minor: int  # efter alla kostnader och avgifter, före skatt
    tax_reserved_minor: int
    after_tax_minor: int
    recent_net_minor: int
    margin_percent: float | None
    lowest_liquid_minor: int
    drawdown_percent: float  # största fall i likvida medel från startkapitalet
    company_stop: bool
    protected_mode: bool
    kill_switch: bool


@dataclass(frozen=True, slots=True)
class Readiness:
    scenario: str
    agents: str
    ready: bool
    recommendation: str
    reasons: tuple[str, ...]
    runs: tuple[RunResult, ...]
    rules: ReadinessRules

    def as_dict(self) -> dict:
        return {"scenario": self.scenario, "agents": self.agents, "ready": self.ready,
                "recommendation": self.recommendation, "reasons": list(self.reasons),
                "rules": asdict(self.rules), "runs": [asdict(r) for r in self.runs]}


def load_readiness_rules(config_dir: Path | str) -> ReadinessRules:
    path = Path(config_dir) / SIMULATION_FILE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{SIMULATION_FILE}: filen saknas i {config_dir}"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError([f"{SIMULATION_FILE}: kan inte tolkas som TOML: {exc}"]) from None
    section = data.get("readiness")
    errors = []
    if data.get("config_version") != 1:
        errors.append(f"{SIMULATION_FILE}: config_version ska vara 1")
    if not isinstance(section, dict):
        raise ConfigError(errors + [f"{SIMULATION_FILE}: [readiness] saknas"])
    for key in section:
        if key not in _READINESS_KEYS:
            errors.append(f"{SIMULATION_FILE}: okänd nyckel readiness.{key}")
    values = {}
    for key in _READINESS_KEYS:
        value = section.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(f"{SIMULATION_FILE}: readiness.{key} ska vara ett heltal ≥ 1")
        values[key] = value
    if not errors and values["min_runs"] < 3:
        errors.append(f"{SIMULATION_FILE}: min_runs ska vara minst 3; en enstaka körning bevisar inget (§29)")
    if not errors and values["recent_days"] > values["min_days"]:
        errors.append(f"{SIMULATION_FILE}: recent_days får inte vara större än min_days")
    if errors:
        raise ConfigError(errors)
    return ReadinessRules(**values)


def evaluate(config, config_dir: Path | str, scenario: Scenario, runs: int | None = None, days: int | None = None,
             agents: str = "scripted", workdir: Path | str | None = None) -> Readiness:
    """Kör `runs` oberoende körningar och bedömer dem mot reglerna. Rör aldrig huvuddatabasen."""
    from ..system import build_system

    require_sim(config)
    if agents == "groq":  # en körning som pausas av kvoten skulle ge en halv bedömning (PR 8)
        raise ValueError("bedömningar körs med scripted eller local; groq bara i simulate start och resume")
    rules = load_readiness_rules(config_dir)
    runs = runs or rules.min_runs
    days = days or max(rules.min_days, scenario.days)
    founder = sorted(config.system.founders)[0]
    results = []
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        for n in range(1, runs + 1):
            sc = replace(scenario, seed=f"{scenario.seed}/utvärdering-{n}", days=days)
            with Database.open(Path(tmp) / f"run-{n}", "sim") as db:
                clock = SimClock(sc.start_date)
                system = build_system(config, db, config_dir, clock=clock)
                ensure_org(system.registry, founder)
                sim = Simulation.start(system, config, sc, founder, clock)
                WorkCycle(sim, system, build_gateway(system, agents, config_dir), agent_data_class(agents)).run()
                results.append(_measure(system, config, sc, rules))
    return _judge(scenario.name, agents, tuple(results), rules, runs, days)


def save_report(readiness: Readiness, data_dir: Path | str) -> tuple[Path, str]:
    text = json.dumps(readiness.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    folder = Path(data_dir) / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"readiness-{readiness.scenario}-{stamp}.json"
    path.write_text(text, encoding="utf-8")
    return path, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _measure(system, config, scenario: Scenario, rules: ReadinessRules) -> RunResult:
    entries = system.ledger.entries("SIM")
    result = compute_result(entries, "SIM")
    tax = system.tax.reserved_minor("SIM")
    last = date.fromisoformat(scenario.start_date) + timedelta(days=scenario.days - 1)
    cutoff = (last - timedelta(days=rules.recent_days - 1)).isoformat()
    recent = compute_result(tuple(e for e in entries if e.recorded_at[:10] >= cutoff and
                                  e.entry_type is not EntryType.CAPITAL_IN), "SIM")
    revenue = result.revenue_minor - result.refunds_minor
    after_tax = result.net_minor - tax
    lowest = _lowest_liquid(entries)
    db = system.db.connection
    company_stop = bool(db.execute("SELECT 1 FROM stop_loss_trips WHERE scope_kind = 'company' LIMIT 1").fetchone())
    protected = bool(db.execute("SELECT 1 FROM operating_mode_events WHERE event = 'entered' LIMIT 1").fetchone())
    kill = bool(db.execute("SELECT 1 FROM kill_switch_events WHERE event = 'engaged' LIMIT 1").fetchone())
    margin = round(after_tax * 100 / revenue, 1) if revenue > 0 else None
    start = config.risk.start_capital.amount_minor
    drawdown = round(max(0, start - lowest) * 100 / start, 1)
    return RunResult(scenario.seed, scenario.days, revenue, result.fees_minor, result.costs_minor, result.net_minor,
                     tax, after_tax, recent.net_minor, margin, lowest, drawdown, company_stop, protected, kill)


def _lowest_liquid(entries) -> int:
    """Lägsta likvida kapital dag för dag (genomförda in- och utbetalningar)."""
    by_day: dict[str, int] = {}
    for e in entries:
        if e.status is not Status.SETTLED:
            continue
        sign = 1 if e.entry_type in (EntryType.REVENUE, EntryType.CAPITAL_IN) else -1
        by_day[e.recorded_at[:10]] = by_day.get(e.recorded_at[:10], 0) + sign * e.amount_minor
    liquid, lowest = 0, None
    for day in sorted(by_day):
        liquid += by_day[day]
        lowest = liquid if lowest is None else min(lowest, liquid)
    return lowest or 0


def _judge(name: str, agents: str, runs: tuple[RunResult, ...], rules: ReadinessRules, n: int, days: int) -> Readiness:
    reasons: list[str] = []
    if n < rules.min_runs:
        reasons.append(f"bara {n} körningar; minst {rules.min_runs} krävs (en enstaka körning bevisar inget, §29)")
    if days < rules.min_days:
        reasons.append(f"bara {days} dagar per körning; minst {rules.min_days} krävs")
    losing = [r.seed for r in runs if r.after_tax_minor <= 0]
    if losing:
        reasons.append(f"{len(losing)} av {len(runs)} körningar saknar vinst efter kostnader, avgifter och skatt")
    fading = [r.seed for r in runs if r.recent_net_minor <= 0]
    if fading:
        reasons.append(f"{len(fading)} av {len(runs)} körningar gick inte med vinst de sista {rules.recent_days} dagarna")
    margins = [r.margin_percent for r in runs if r.margin_percent is not None]
    median = statistics.median(margins) if margins else None
    if median is None or median < rules.min_margin_percent:
        shown = "ingen försäljning" if median is None else f"{median:.1f} %"
        reasons.append(f"medianmarginalen efter skatt är {shown}; minst {rules.min_margin_percent} % krävs")
    for flag, text in (("company_stop", "stop-loss för hela företaget"), ("protected_mode", "skyddat driftläge"),
                       ("kill_switch", "nödstopp")):
        hit = sum(1 for r in runs if getattr(r, flag))
        if hit:
            reasons.append(f"{hit} körningar utlöste {text}")
    deep = [r for r in runs if r.drawdown_percent > rules.max_drawdown_percent]
    if deep:
        worst = max(r.drawdown_percent for r in deep)
        reasons.append(f"{len(deep)} körningar föll mer än {rules.max_drawdown_percent} % från startkapitalet "
                       f"(värst {worst:.1f} %)")
    ready = not reasons
    if ready:
        recommendation = (f"Redo för en första riktig investering på {rules.first_real_investment / 100:.0f} kr. "
                          "Det kräver grundarnas uttryckliga godkännande och Fas 7:s villkor (§55). Inga riktiga "
                          f"pengar används automatiskt. Att öka till {rules.next_real_investment / 100:.0f} kr bedöms "
                          "först på resultat från riktiga pengar.")
    else:
        recommendation = "Inte redo för riktiga pengar. Fortsätt i simuleringen och förbättra strategin."
    return Readiness(name, agents, ready, recommendation, tuple(reasons), runs, rules)
