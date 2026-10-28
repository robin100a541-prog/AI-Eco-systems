"""`python -m aie registry list|show|import|status|dependency` (PR 4, D-056, D-059).

    python -m aie registry list
    python -m aie registry show platform plattform-a
    python -m aie registry import --as yorgo                     # config/registry/*.toml
    python -m aie registry status platform plattform-a approved --as yorgo --note "villkoren lästa"
    python -m aie registry dependency                            # andel av intäkterna per plattform (D-059)

Registret byggs med hela systemet, så att samma spärrar gäller här som i simuleringen: bedömningen
före start (D-058) och plattformsberoendet (D-059).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import runtime
from ..config import ConfigError
from .registry import KINDS, RegistryError
from .seed import import_dir


def registry(config_dir: Path, action: str, kind: str | None = None, key: str | None = None,
             status: str | None = None, founder: str | None = None, note: str = "") -> int:
    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            from ..system import build_system

            try:
                register = build_system(config, db, config_dir).register
            except ConfigError as exc:
                raise runtime.StartupError(f"FEL: {exc}") from exc
            try:
                if action == "list":
                    for k in KINDS:
                        for e in register.all(k):
                            print(f"{k:10} {e.key:20} {e.status:12} version {e.version}  {e.data.get('name', e.data.get('description', ''))}")
                    return 0
                if action == "show":
                    entry = register.get(kind, key)
                    if entry is None:
                        print(f"{kind} {key} finns inte.", file=sys.stderr)
                        return 1
                    print(json.dumps({"kind": entry.kind, "key": entry.key, "version": entry.version,
                                      "status": entry.status, "actor": entry.actor, "note": entry.note,
                                      "at": entry.at, "data": entry.data}, ensure_ascii=False, indent=2))
                    return 0
                if action == "dependency":
                    _print_dependency(register.dependency.report())
                    return 0
                if action == "import":
                    for line in import_dir(register, founder, config_dir):
                        print(line)
                    return 0
                entry = register.set_status(founder, kind, key, status, note)
                print(f"{kind} {key}: version {entry.version}, status {entry.status}")
                return 0
            except (RegistryError, ConfigError) as exc:
                print(f"FEL: {exc}", file=sys.stderr)
                return 1
    except runtime.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1


def _print_dependency(report: dict) -> None:
    limits = report["limits"]
    print(f"Intäkter de senaste 90 dagarna: {report['total_revenue_minor']}. "
          f"MAX_PLATFORM_REVENUE_SHARE {limits['MAX_PLATFORM_REVENUE_SHARE']}, "
          f"MIN_ACTIVE_PLATFORMS {limits['MIN_ACTIVE_PLATFORMS']}, "
          f"oberoende godkända eller aktiva plattformar {report['active_independent']}.")
    for row in report["groups"]:
        print(f"  {', '.join(row['platforms']):30} {row['revenue_minor']:>10} {row['percent']:>6} %")
        if "action" in row:
            print(f"    -> {row['action']}")
    if not report["groups"]:
        print("  inga intäkter: ingen andel att mäta")
