"""`python -m aie results import|list|report` (PR 10, D-062): utfall från verkligheten.

    python -m aie results import utfall.csv --as yorgo
    python -m aie results list
    python -m aie results report mallar

Kolumnerna och reglerna står i `results/store.py` och i `docs/setup.md`. Allt som importeras märks
"verifierat i verkligheten". Prognosen i rapporten är simulerad och märks så.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import runtime
from ..config import ConfigError
from .store import MIN_DAYS, VERIFIED, ResultError


def results(config_dir: Path, action: str, target: str | None = None, founder: str | None = None) -> int:
    from ..system import build_system

    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            try:
                store = build_system(config, db, config_dir).results
            except ConfigError as exc:
                raise runtime.StartupError(f"FEL: {exc}") from exc
            try:
                if action == "import":
                    try:
                        text = Path(target).read_text(encoding="utf-8")
                    except OSError as exc:
                        raise ResultError(f"kan inte läsa {target}: {exc}") from None
                    new, known = store.import_csv(founder, text)
                    print(f"{new} nya rader importerade ({VERIFIED}), {known} fanns redan.")
                    return 0
                if action == "list":
                    names = store.initiatives()
                    if not names:
                        print("Inga utfall importerade.")
                    for name in names:
                        for o in store.observed(name):
                            print(f"{name:20} {o.currency} {o.days:>3} dagar {o.first_day}–{o.last_day}: "
                                  f"{o.orders} order, netto {o.net_minor} ({VERIFIED})")
                    return 0
                _print_report(store.report(target))
                return 0
            except ResultError as exc:
                print(f"FEL: {exc}", file=sys.stderr)
                return 1
    except runtime.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1


def _print_report(report: dict) -> None:
    print(f"Prognos mot utfall för {report['initiative']}")
    if not report["results"]:
        print("  inga utfall importerade")
    for r in report["results"]:
        f, o = r["forecast"], r["outcome"]
        print(f"  {r['currency']}, {r['days']} dagar {r['period']} ({VERIFIED}; källor: {', '.join(r['sources'])})")
        if not r["enough_days"]:
            print(f"    färre än {MIN_DAYS} dagar: utfallet ersätter inga antaganden än")
        nets = ", ".join(f"{k} {v}" for k, v in f["net_per_day_minor"].items()) or "ingen godkänd bedömning"
        print(f"    netto per dag:   utfall {o['net_per_day_minor']:>8}  prognos (simulerat, SIM) {nets}")
        for key, label in (("visitors_per_day", "besökare per dag"), ("conversion_bp", "konvertering, bp"),
                           ("refund_bp", "återbetalningar, bp")):
            print(f"    {label + ':':17}utfall {str(o[key]):>8}  prognos (antagande i registret) {f[key]}")
    print(f"  {report['note']}")
