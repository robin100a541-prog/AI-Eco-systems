"""Fyller SIM-databasen med testdata för kommandocentralen (dashboard D0b).

    py scripts/seed_sim.py [--config-dir config] [--days 30] [--scenario normal] [--as yorgo]

Kör simuleringen och lägger 3 väntande godkännanden via kärnans kö. Vägrar allt utom miljön sim med valutan
SIM, och en datamapp som redan har en körning. Logiken finns i `aie.simulation.seed`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aie.simulation.run import SimulationError  # noqa: E402
from aie.simulation.seed import seed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Testdata i SIM för kommandocentralen (D0b)")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--scenario", default="normal")
    parser.add_argument("--as", dest="founder", default="yorgo")
    args = parser.parse_args(argv)
    try:
        result = seed(args.config_dir, days=args.days, scenario=args.scenario, founder=args.founder)
    except SimulationError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    print(f"Klar: {result.database} ({result.days} dagar i SIM, {result.pending} väntande godkännanden, "
          f"revisionslogg {'OK' if result.audit_ok else 'TRASIG'})")
    return 0 if result.audit_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
