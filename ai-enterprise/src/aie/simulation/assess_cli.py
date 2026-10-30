"""`python -m aie assess run|approve|reject|list|show` (PR 6, D-058).

    python -m aie assess run mallar --as res-1 [--runs 5] [--days 90]
    python -m aie assess list mallar
    python -m aie assess show 3
    python -m aie assess approve 3 --as yorgo --note "antagandena är rimliga"

`run` kör initiativet i normalt, pessimistiskt och noll-försäljningsscenario och sparar bedömningen. Den
körs bara i miljön sim. `approve` kan bara godkänna en bedömning som är redo. Utan godkänd bedömning med
exakt samma parametrar kan initiativet aldrig godkännas, listas eller få utgifter.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import runtime
from ..config import ConfigError
from ..registry import AssessmentError
from .assessment import assess_initiative
from .run import SimulationError


def assess(config_dir: Path, action: str, target: str | None = None, actor: str | None = None,
           note: str = "", runs: int | None = None, days: int | None = None) -> int:
    from ..system import build_system

    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            try:
                system = build_system(config, db, config_dir)
            except ConfigError as exc:
                raise runtime.StartupError(f"FEL: {exc}") from exc
            store = system.register.assessments
            try:
                if action == "run":
                    a = assess_initiative(config, config_dir, system.register, target, actor, runs, days,
                                          results=system.results)
                    _print(a)
                    return 0
                if action == "list":
                    for a in store.for_initiative(target):
                        print(f"#{a.assessment_id} {a.at} {'redo' if a.ready else 'inte redo'} "
                              f"{a.decision or 'väntar på grundare'}")
                    return 0
                if action == "show":
                    a = store.get(int(target))
                    if a is None:
                        print(f"bedömning {target} finns inte", file=sys.stderr)
                        return 1
                    _print(a, full=True)
                    return 0
                a = (store.approve if action == "approve" else store.reject)(actor, int(target), note)
                print(f"Bedömning #{a.assessment_id} är {a.decision} av {a.decided_by}.")
                return 0
            except (AssessmentError, SimulationError, ConfigError, ValueError) as exc:
                print(f"FEL: {exc}", file=sys.stderr)
                return 1
    except runtime.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1


def _print(a, full: bool = False) -> None:
    r = a.result
    print(f"Bedömning #{a.assessment_id} av {a.initiative} på {a.platform}: {'REDO' if a.ready else 'INTE REDO'}")
    print(r.get("disclaimer", ""))
    for name, s in r.get("scenarios", {}).items():
        print(f"  {name}: median efter skatt och fasta kostnader {s['median_adjusted_after_tax_minor']}, "
              f"netto per dag {s['daily_net_minor']}")
    for reason in r.get("reasons", []):
        print(f"  - {reason}")
    for v in r.get("verified", []):
        print(f"  {v}")
    print("  Antaganden: " + "; ".join(r.get("assumptions", [])))
    sens = [s for s in r.get("sensitivity", []) if "parameter" in s][:3]
    if sens:
        print("  Påverkar mest: " + ", ".join(f"{s['parameter']} (±20 % ger {s['minus_20']}…{s['plus_20']} per dag)"
                                              for s in sens))
    if full:
        print(json.dumps(r, ensure_ascii=False, indent=2))
