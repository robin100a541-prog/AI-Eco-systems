"""`python -m aie report daily|periodic|monitor` (FR-21, FR-22, FR-24). Läser bara; ändrar inget.

    python -m aie report daily --day 2027-01-05
    python -m aie report periodic --from 2027-01-01 --to 2027-01-31
    python -m aie report monitor [--from 2027-01-01]

Utan datum används dagens datum (simuleringens affärstid om en körning finns).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from .. import runtime
from ..config import ConfigError


def report(config_dir: Path, kind: str, day: str | None, start: str | None, end: str | None) -> int:
    from ..simulation.market import SimClock
    from ..simulation.run import stored_run
    from ..system import build_system
    from .daily import daily_report
    from .monitor import monitor
    from .periodic import periodic_report

    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            run = stored_run(db)
            clock = SimClock(run["start_date"]) if run else None
            system = build_system(config, db, config_dir, clock=clock)
            last = max((e.economic_date for e in system.ledger.entries(system.currency)), default=None)
            today = last or datetime.now(UTC).date().isoformat()
            if kind == "daily":
                print(daily_report(system, day or today).render(), end="")
            elif kind == "periodic":
                print(periodic_report(system, start or today, end or today).render(), end="")
            else:
                findings = monitor(system, start or "")
                for f in findings:
                    print(f"{f.kind}\t{f.subject}\t{f.detail}")
                print(f"{len(findings)} fynd")
            return 0
    except (runtime.StartupError, ConfigError, ValueError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
