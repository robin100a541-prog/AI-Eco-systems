"""`python -m aie simulate start|resume|status|evaluate` (Fas 6b-2, D-043, D-048).

    python -m aie simulate start --scenario normal --as yorgo [--days 10] [--agents scripted|local|groq]
    python -m aie simulate resume [--days 10] [--agents scripted|local|groq]
    python -m aie simulate status
    python -m aie simulate evaluate --scenario normal [--runs 5] [--days 90] [--agents scripted|local]

`evaluate` kör scenariot många gånger med olika seed, i tillfälliga databaser, och bedömer om
affärsmodellen är lönsam nog för en första riktig investering (D-048). Det är en rekommendation,
aldrig en handling. Rapporten sparas i `<data_dir>/reports/`.

`start` kräver en tom datamapp (en körning per databas, D-042) och registrerar simuleringens
organisation om registret är tomt. `resume` fortsätter där körningen slutade, även efter en krasch eller
ett stopp. `--agents scripted` (standard) kör de deterministiska agenterna. `--agents local` använder
en lokal modell (Ollama) ur `providers.toml`. `--agents groq` använder Groqs gratisnivå med nyckeln i
`GROQ_API_KEY` (se `docs/setup.md`). Den får bara simulerade data. När kvoten är slut pausas körningen, och
`resume` fortsätter senare. Varje dag skrivs ut med order, åtgärder och pauser.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import runtime
from ..authorization import load_permissions
from ..config import ConfigError
from ..ledger import compute_result
from .agents import agent_data_class, build_gateway, ensure_org
from .cycle import WorkCycle
from .market import SimClock
from .run import Simulation, SimulationError, stored_run
from .scenario import load_scenario


def simulate(config_dir: Path, action: str, scenario: str | None = None, founder: str | None = None,
             days: int | None = None, agents: str = "scripted", runs: int | None = None) -> int:
    from ..system import build_system

    try:
        config = runtime._load(config_dir, console=False)
        if action == "evaluate":
            return _evaluate(config, config_dir, scenario, runs, days, agents)
        with runtime._open(config) as db:
            run = stored_run(db)
            if action == "status":
                return _status(db, run)
            if action == "start" and run is not None:
                raise runtime.StartupError("FEL: datamappen har redan en körning; använd resume eller en ny datamapp")
            if action == "resume" and run is None:
                raise runtime.StartupError("FEL: ingen körning att återuppta; använd start")
            try:
                if action == "start":
                    departments = {m.department for m in load_permissions(config_dir).roles.values()}
                    sc = load_scenario(config_dir, scenario, departments, frozenset(config.system.founders))
                    clock = SimClock(sc.start_date)
                    system = build_system(config, db, config_dir, clock=clock)
                    ensure_org(system.registry, founder)
                    sim = Simulation.start(system, config, sc, founder, clock)
                else:
                    clock = SimClock(run["start_date"])
                    system = build_system(config, db, config_dir, clock=clock)
                    sim = Simulation.resume(system, config, clock)
                cycle = WorkCycle(sim, system, build_gateway(system, agents, config_dir), agent_data_class(agents))
            except (ConfigError, SimulationError, ValueError) as exc:
                raise runtime.StartupError(f"FEL: {exc}") from exc
            print(f"Körning {sim.run_id}: scenario {sim.scenario.name}, dag {sim.last_day} av {sim.scenario.days} "
                  f"(agenter: {agents}, bara SIM)")
            for summary in cycle.run(days):
                print(_line(summary))
            if cycle.paused:
                print(f"PAUSAD: {cycle.paused}")
            net = compute_result(system.ledger.entries("SIM"), "SIM").net_minor
            check = system.audit.verify()
            print(f"Klar till dag {sim.last_day} av {sim.scenario.days}. Nettoresultat {net} SIM, "
                  f"reserverad skatt {system.tax.reserved_minor()} SIM, revisionslogg {'OK' if check.ok else 'TRASIG'}.")
            return 0 if check.ok else 1
    except runtime.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1


def _evaluate(config, config_dir: Path, scenario: str, runs: int | None, days: int | None, agents: str) -> int:
    from .readiness import evaluate, save_report

    try:
        departments = {m.department for m in load_permissions(config_dir).roles.values()}
        sc = load_scenario(config_dir, scenario, departments, frozenset(config.system.founders))
        result = evaluate(config, config_dir, sc, runs, days, agents)
    except (ConfigError, SimulationError, ValueError) as exc:
        raise runtime.StartupError(f"FEL: {exc}") from exc
    print(f"Bedömning av {sc.name}: {len(result.runs)} körningar à {result.runs[0].days if result.runs else 0} dagar "
          f"(agenter: {agents}, bara SIM)")
    for r in result.runs:
        margin = "-" if r.margin_percent is None else f"{r.margin_percent:.1f} %"
        print(f"  {r.seed}: intäkter {r.revenue_minor}, avgifter {r.fees_minor}, kostnader {r.costs_minor}, "
              f"efter skatt {r.after_tax_minor}, sista {result.rules.recent_days} dagarna {r.recent_net_minor}, "
              f"marginal {margin}, fall {r.drawdown_percent:.1f} %")
    for reason in result.reasons:
        print(f"  - {reason}")
    print(("REKOMMENDATION: " if result.ready else "RESULTAT: ") + result.recommendation)
    path, digest = save_report(result, config.system.data_dir)
    print(f"Rapport: {path} (SHA-256 {digest})")
    return 0


def _line(d: dict) -> str:
    orders = sum(v["orders"] for v in d["initiatives"].values())
    done = sum(1 for a in d.get("actions", ()) if a["outcome"] == "done")
    blocked = sum(1 for a in d.get("actions", ()) if a["outcome"] != "done") + len(d.get("rejected", ()))
    extra = f" PAUSAD: {d['paused']}" if d["paused"] else ""
    if d.get("stopped"):
        extra += f" stoppade: {', '.join(d['stopped'])}"
    return f"dag {d['day']:>3} {d['date']}: {orders} order, {done} åtgärder, {blocked} nekade{extra}"


def _status(db, run) -> int:
    if run is None:
        print("Ingen simuleringskörning i datamappen.")
        return 0
    last = db.connection.execute("SELECT COALESCE(MAX(day), 0) FROM simulation_days WHERE run_id = ?",
                                 (run["run_id"],)).fetchone()[0]
    print(f"Körning {run['run_id']}: scenario {run['scenario']} (seed {run['seed']}), startad av {run['created_by']}")
    print(f"Dag {last} av {run['days']}{' (klar)' if last >= run['days'] else ''}")
    return 0
