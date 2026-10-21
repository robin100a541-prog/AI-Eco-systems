"""Kommandoradsgränssnitt: `python -m aie <kommando>` (ARCHITECTURE.md §3.6).

Fas 1.1–1.2 har bara `check-config`. `init`, `start`, `stop` och `status` byggs i 1.6.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config


def _check_config(config_dir: Path) -> int:
    """Läser och validerar konfigurationen. Kod 0 = giltig, kod 1 = ogiltig (FR-02)."""
    try:
        config = load_config(config_dir)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    for warning in config.warnings:
        print(f"VARNING: {warning}")
    system = config.system
    print(
        f"Konfiguration OK (miljö: {system.environment}, valuta: {system.base_currency}, "
        f"config_version: {system.config_version})"
    )
    return 0


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
    if args.command == "check-config":
        return _check_config(args.config_dir)
    raise AssertionError(f"okänt kommando: {args.command}")  # argparse släpper inte igenom andra


if __name__ == "__main__":
    raise SystemExit(main())
