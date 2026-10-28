"""Kommandoradsgränssnitt: `python -m aie <kommando>` (ARCHITECTURE.md §3.6).

Kommandon (kod 0 = lyckades, kod 1 = fel som är utskrivet och loggat):
- `check-config`  läs och validera konfigurationen (Fas 1.2)
- `init`          skapa eller uppgradera databasen (Fas 1.6)
- `start`         starta systemet och kör tills `stop`, Ctrl+C eller SIGTERM (Fas 1.6)
- `stop`          be det körande systemet stanna och vänta tills det har stängt ned (Fas 1.6)
- `status`        visa driftläget och kontrollera revisionsloggen (Fas 1.6)
- `approvals`     grundarnas godkännandekö (Fas 3, D-019)
- `manual`        besvara förfrågningar till manual-providern (Fas 3, D-005)
- `kill`          nödstopp: status, engage, release (Fas 4e, D-030)
- `assess`        bedömning före start: run, list, show, approve, reject (PR 6, D-058)
- `research`      läs en känd offentlig webbsida (PR 5, D-057)
- `registry`      plattforms- och initiativregistret: list, show, import, status, dependency (PR 4, D-056, D-059)
- `spend`         godkännanden av enskilda utgifter: list, approve, reject (F5, D-053)
- `simulate`      affärssimulering med SIM: start, resume, status, evaluate (Fas 6, D-042, D-043, D-048)

Varje körning loggas till `<log_dir>/aie.log` (FR-04). Sökvägarna i `config/system.toml`
gäller relativt mappen kommandot körs från.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, runtime
from .config import ConfigError, load_config
from .monitoring import LoggingSetupError, get_logger, setup_logging, shutdown_logging


def _check_config(config_dir: Path) -> int:
    """Läser och validerar konfigurationen. Kod 0 = giltig, kod 1 = ogiltig (FR-02).

    Kommandot skriver själv sitt resultat, så loggningen går bara till filen (console=False)
    för att inte visa samma rad två gånger.
    """
    try:
        config = load_config(config_dir)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        runtime._log_config_errors(exc)
        return 1

    system = config.system
    try:
        setup_logging(system.log_dir, system.log_level, console=False)
    except LoggingSetupError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    log = get_logger("cli")

    for warning in config.warnings:
        print(f"VARNING: {warning}")
        log.warning("konfigurationsvarning: %s", warning)
    print(
        f"Konfiguration OK (miljö: {system.environment}, valuta: {system.base_currency}, "
        f"config_version: {system.config_version})"
    )
    log.info(
        "check-config: konfigurationen är giltig",
        extra={
            "fields": {"environment": system.environment, "config_dir": str(config_dir)}
        },
    )
    return 0


def _positive(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("måste vara större än 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aie", description="AI Enterprise System")
    parser.add_argument("--version", action="version", version=f"aie {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="kommando")

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument(
            "--config-dir",
            type=Path,
            default=Path("config"),
            help="mapp med system.toml och risk_limits.toml (standard: ./config)",
        )
        return sub

    add("check-config", "läs och validera config/*.toml")
    add("init", "skapa eller uppgradera databasen")
    start = add("start", "starta systemet och kör tills det ombeds stanna")
    start.add_argument(
        "--poll-seconds",
        type=_positive,
        default=runtime.DEFAULT_POLL_SECONDS,
        help="hur ofta en stoppbegäran kontrolleras (standard: 1)",
    )
    stop = add("stop", "be systemet stanna och vänta tills det har stängt ned")
    stop.add_argument(
        "--wait-seconds",
        type=_positive,
        default=runtime.DEFAULT_STOP_WAIT_SECONDS,
        help="hur länge stop väntar innan det ger upp med kod 1 (standard: 30)",
    )
    add("status", "visa driftläget och kontrollera revisionsloggen")
    approvals = add("approvals", "grundarnas godkännandekö: list, approve eller reject (D-019)")
    approvals.add_argument("action", choices=("list", "approve", "reject"))
    approvals.add_argument("request_id", type=int, nargs="?", help="förfrågans nummer (för approve och reject)")
    approvals.add_argument("--as", dest="founder", help="vilken grundare som röstar (en av founders i system.toml)")
    approvals.add_argument("--note", default="", help="motivering; krävs vid reject")
    manual = add("manual", "manuella svar till manual-providern: list, show eller answer (D-005)")
    manual.add_argument("action", choices=("list", "show", "answer"))
    manual.add_argument("request_id", nargs="?", help="förfrågans id (för show och answer)")
    manual.add_argument("--as", dest="founder", help="vilken grundare som svarar (en av founders i system.toml)")
    manual.add_argument("--file", dest="answer_file", help="fil med svaret, eller - för stdin")
    kill = add("kill", "nödstopp: status, engage eller release (SR-07, §38, D-030)")
    kill.add_argument("action", choices=("status", "engage", "release"))
    kill.add_argument("--as", dest="founder", help="vilken grundare som agerar (en av founders i system.toml)")
    kill.add_argument("--reason", default="", help="varför; krävs vid engage och release")
    dev = add("dev-agent", "utvecklaragenten: run eller open-pr (D-050)")
    dev.add_argument("action", choices=("run", "open-pr"))
    dev.add_argument("--branch", default="claude/dev-agent-local", help="gren för ändringen (run)")
    dev.add_argument("--out", type=Path, default=Path("dev-agent-result.json"), help="resultatfil")
    dev.add_argument("--result", type=Path, default=Path("dev-agent-result.json"), help="resultatfil (open-pr)")
    ass = add("assess", "bedömning före start: run, list, show, approve eller reject (PR 6, D-058)")
    ass.add_argument("action", choices=("run", "list", "show", "approve", "reject"))
    ass.add_argument("target", help="initiativ (run, list) eller bedömningens nummer (show, approve, reject)")
    ass.add_argument("--as", dest="actor", help="vem som kör (agent eller grundare) eller beslutar (grundare)")
    ass.add_argument("--note", default="", help="motivering; krävs vid reject")
    ass.add_argument("--runs", type=int, help="körningar per scenario (standard: min_runs)")
    ass.add_argument("--days", type=int, help="dagar per körning (standard: min_days)")
    res = add("research", "läs en känd offentlig webbsida som en agent med research.search (PR 5, D-057)")
    res.add_argument("action", choices=("fetch", "history"))
    res.add_argument("url", nargs="?")
    res.add_argument("--agent", help="agenten som hämtar (måste ha research.search)")
    reg = add("registry", "plattforms- och initiativregistret: list, show, import, status eller dependency "
                          "(PR 4, D-056, D-059)")
    reg.add_argument("action", choices=("list", "show", "import", "status", "dependency"))
    reg.add_argument("kind", nargs="?", choices=("platform", "initiative"))
    reg.add_argument("key", nargs="?")
    reg.add_argument("status", nargs="?", help="ny status (för status)")
    reg.add_argument("--as", dest="founder", help="vilken grundare som agerar (för import och status)")
    reg.add_argument("--note", default="", help="motivering (för status)")
    sp = add("spend", "godkännanden av enskilda utgifter: list, approve eller reject (F5, D-053)")
    sp.add_argument("action", choices=("list", "approve", "reject"))
    sp.add_argument("approval_id", type=int, nargs="?", help="förfrågans nummer (för approve och reject)")
    sp.add_argument("--as", dest="founder", help="vilken grundare som beslutar")
    sp.add_argument("--note", default="", help="motivering; krävs vid reject")
    sim = add("simulate", "affärssimulering med SIM: start, resume, status eller evaluate (Fas 6, D-042, D-043, D-048)")
    sim.add_argument("action", choices=("start", "resume", "status", "evaluate"))
    sim.add_argument("--scenario", help="scenario i config/scenarios/ (för start och evaluate)")
    sim.add_argument("--runs", type=int, help="evaluate: antal körningar (standard: min_runs i simulation.toml)")
    sim.add_argument("--as", dest="founder", help="vilken grundare som startar (för start)")
    sim.add_argument("--days", type=int, help="hur många dagar som körs nu (standard: resten av scenariot)")
    sim.add_argument("--agents", choices=("scripted", "local"), default="scripted",
                     help="scripted = deterministiska agenter (standard), local = lokal modell via Ollama")
    return parser


def _assess(args: argparse.Namespace) -> int:
    from .simulation.assess_cli import assess  # importeras bara när kommandot används

    if args.action in ("run", "approve", "reject") and not args.actor:
        print("FEL: run, approve och reject kräver --as", file=sys.stderr)
        return 1
    return assess(args.config_dir, args.action, args.target, args.actor, args.note, args.runs, args.days)


def _research(args: argparse.Namespace) -> int:
    from .research.cli import research  # importeras bara när kommandot används

    if args.action == "fetch" and (not args.url or not args.agent):
        print("FEL: fetch kräver en URL och --agent <agent>", file=sys.stderr)
        return 1
    return research(args.config_dir, args.action, args.url, args.agent)


def _registry(args: argparse.Namespace) -> int:
    from .registry.cli import registry  # importeras bara när kommandot används

    if args.action in ("show", "status") and (not args.kind or not args.key):
        print("FEL: show och status kräver typ och nyckel, till exempel platform plattform-a", file=sys.stderr)
        return 1
    if args.action in ("import", "status") and not args.founder:
        print("FEL: import och status kräver --as <grundare>", file=sys.stderr)
        return 1
    if args.action == "status" and (not args.status or not args.note.strip()):
        print("FEL: status kräver ny status och --note", file=sys.stderr)
        return 1
    return registry(args.config_dir, args.action, args.kind, args.key, args.status, args.founder, args.note)


def _spend(args: argparse.Namespace) -> int:
    from .budget.cli import spend  # importeras bara när kommandot används

    if args.action != "list" and (args.approval_id is None or not args.founder):
        print("FEL: approve och reject kräver förfrågans nummer och --as <grundare>", file=sys.stderr)
        return 1
    return spend(args.config_dir, args.action, args.approval_id, args.founder, args.note)


def _simulate(args: argparse.Namespace) -> int:
    from .simulation.cli import simulate  # importeras bara när kommandot används

    if args.action == "start" and (not args.scenario or not args.founder):
        print("FEL: start kräver --scenario <namn> och --as <grundare>", file=sys.stderr)
        return 1
    if args.action == "evaluate" and not args.scenario:
        print("FEL: evaluate kräver --scenario <namn>", file=sys.stderr)
        return 1
    if args.runs is not None and args.runs < 1:
        print("FEL: --runs måste vara minst 1", file=sys.stderr)
        return 1
    if args.days is not None and args.days < 1:
        print("FEL: --days måste vara minst 1", file=sys.stderr)
        return 1
    return simulate(args.config_dir, args.action, args.scenario, args.founder, args.days, args.agents, args.runs)


def _kill(args: argparse.Namespace) -> int:
    from .risk.cli import kill  # importeras bara när kommandot används

    if args.action != "status" and (not args.founder or not args.reason.strip()):
        print("FEL: engage och release kräver --as <grundare> och --reason", file=sys.stderr)
        return 1
    return kill(args.config_dir, args.action, args.founder, args.reason)


def _dev_agent(args: argparse.Namespace) -> int:
    from .dev_agent import cli  # importeras bara när kommandot används

    if args.action == "run":
        return cli.run(args.config_dir, args.branch, args.out)
    return cli.open_pr(args.result)


def _manual(args: argparse.Namespace) -> int:
    from .llm.cli import manual  # importeras bara när kommandot används

    if args.action != "list" and not args.request_id:
        print("FEL: show och answer kräver förfrågans id", file=sys.stderr)
        return 1
    return manual(args.config_dir, args.action, args.request_id, args.founder, args.answer_file)


def _approvals(args: argparse.Namespace) -> int:
    from .governance.cli import approvals  # importeras bara när kommandot används

    if args.action != "list" and (args.request_id is None or not args.founder):
        print("FEL: approve och reject kräver förfrågans nummer och --as <grundare>", file=sys.stderr)
        return 1
    return approvals(args.config_dir, args.action, args.request_id, args.founder, args.note)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {
        "check-config": lambda: _check_config(args.config_dir),
        "init": lambda: runtime.init(args.config_dir),
        "start": lambda: runtime.start(args.config_dir, args.poll_seconds),
        "stop": lambda: runtime.stop(args.config_dir, args.wait_seconds),
        "status": lambda: runtime.status(args.config_dir),
        "approvals": lambda: _approvals(args),
        "manual": lambda: _manual(args),
        "dev-agent": lambda: _dev_agent(args),
        "kill": lambda: _kill(args),
        "simulate": lambda: _simulate(args),
        "spend": lambda: _spend(args),
        "registry": lambda: _registry(args),
        "research": lambda: _research(args),
        "assess": lambda: _assess(args),
    }
    try:
        return commands[args.command]()
    finally:
        shutdown_logging()  # släpper loggfilen


if __name__ == "__main__":
    raise SystemExit(main())
