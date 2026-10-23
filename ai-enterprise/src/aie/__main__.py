"""Kommandoradsgränssnitt: `python -m aie <kommando>` (ARCHITECTURE.md §3.6).

Kommandon (kod 0 = lyckades, kod 1 = fel som är utskrivet och loggat):
- `check-config`  läs och validera konfigurationen (Fas 1.2)
- `init`          skapa eller uppgradera databasen (Fas 1.6)
- `start`         starta systemet och kör tills `stop`, Ctrl+C eller SIGTERM (Fas 1.6)
- `stop`          be det körande systemet stanna och vänta tills det har stängt ned (Fas 1.6)
- `status`        visa driftläget och kontrollera revisionsloggen (Fas 1.6)

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
    return parser


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
    }
    try:
        return commands[args.command]()
    finally:
        shutdown_logging()  # släpper loggfilen


if __name__ == "__main__":
    raise SystemExit(main())
