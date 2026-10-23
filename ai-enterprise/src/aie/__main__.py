"""Kommandoradsgränssnitt: `python -m aie <kommando>` (ARCHITECTURE.md §3.6).

Fas 1.1–1.2 har bara `check-config`. `init`, `start`, `stop` och `status` byggs i 1.6.
Från Fas 1.3 loggas varje körning till `<log_dir>/aie.log` (FR-04).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .monitoring import LoggingSetupError, get_logger, setup_logging, shutdown_logging

# När konfigurationen är ogiltig är log_dir okänd. Felen loggas då här, relativt
# mappen kommandot körs från, samma som standardvärdet i config/system.toml.
FALLBACK_LOG_DIR = Path("logs")


def _check_config(config_dir: Path) -> int:
    """Läser och validerar konfigurationen. Kod 0 = giltig, kod 1 = ogiltig (FR-02).

    Kommandot skriver själv sitt resultat, så loggningen går bara till filen (console=False)
    för att inte visa samma rad två gånger.
    """
    try:
        config = load_config(config_dir)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        _log_config_errors(exc)
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
        extra={"fields": {"environment": system.environment, "config_dir": str(config_dir)}},
    )
    return 0


def _log_config_errors(exc: ConfigError) -> None:
    """Loggar konfigurationsfelen i FALLBACK_LOG_DIR. Går det inte är felen redan utskrivna."""
    try:
        setup_logging(FALLBACK_LOG_DIR, console=False)
    except LoggingSetupError:
        return
    log = get_logger("config")
    for error in exc.errors:
        log.error("konfigurationsfel: %s", error)
    for warning in exc.warnings:
        log.warning("konfigurationsvarning: %s", warning)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aie", description="AI Enterprise System")
    parser.add_argument("--version", action="version", version=f"aie {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="kommando")

    check = commands.add_parser("check-config", help="läs och validera config/*.toml")
    check.add_argument(
        "--config-dir",
        type=Path,
        default=Path("config"),
        help="mapp med system.toml och risk_limits.toml (standard: ./config)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check-config":
            return _check_config(args.config_dir)
    finally:
        shutdown_logging()  # släpper loggfilen
    raise AssertionError(f"okänt kommando: {args.command}")  # argparse släpper inte igenom andra


if __name__ == "__main__":
    raise SystemExit(main())
