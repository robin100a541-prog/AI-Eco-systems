"""`python -m aie pilot ...` (Fas 7).

    python -m aie pilot ideas --as robin [--agents rule|groq] [--usd-sek 10.5] [--out products]
                              [--report docs/reports/7c-llm-quality.md]

`ideas`: produktagenten föreslår tre produkter, CFO och risk bedömer, CEO beslutar (beslutsloggen,
tvister och eskalering), och den valda produkten skrivs till `products/<id>/`. Bara offentliga data
skickas till modellen (inga belopp ur ledgern, inga kunduppgifter). Med `--agents rule` görs inga
nätverksanrop. Kursen USD→SEK är ett antagande som anges vid körningen.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import runtime
from ..config import ConfigError


def gateway_for(gov, db, mode: str, config_dir: Path):
    from types import SimpleNamespace

    from ..llm.providers import RuleProvider
    from ..llm.router import ProviderRouter, QuotaLedger, Slot
    from ..simulation.agents import build_gateway

    holder = SimpleNamespace(db=db, audit=gov.audit, engine=gov.engine)
    if mode == "groq":
        return build_gateway(holder, "groq", config_dir)
    from ..llm.gateway import LLMGateway

    slots = (Slot(RuleProvider("pilot-rule", lambda req: "{}"), 1_000, 1_000_000),)
    return LLMGateway(ProviderRouter(slots, QuotaLedger(db), gov.audit), gov.engine, gov.audit)


def ideas(config_dir: Path, founder: str, mode: str, usd_sek: float, out: Path, report: Path | None) -> int:
    from ..governance.cli import build
    from ..simulation.agents import ensure_org
    from .decide import quality_report, run_cycle
    from .product import propose
    from .writer import write_content, write_product

    try:
        config = runtime._load(config_dir, console=False)
        if founder not in config.system.founders:
            print(f"FEL: {founder!r} är ingen grundare", file=sys.stderr)
            return 1
        with runtime._open(config) as db:
            gov = build(config, db, config_dir)
            ensure_org(gov.registry, founder)
            gateway = gateway_for(gov, db, mode, config_dir)
            proposed, log = propose(gateway)
            result = run_cycle(gov, gateway, proposed, founder, config.risk, usd_sek)
            content, source = write_content(gateway, result.chosen)
            folder = write_product(result.chosen, content, source, out)
    except (ConfigError, ValueError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    text = quality_report(result, log, proposed) + f"\nProduktens text: {source}. Filer: `{folder}`.\n"
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(text, encoding="utf-8")
    print(text)
    decision = result.decision
    print(f"Beslut: {type(decision).__name__} #{getattr(decision, 'decision_id', getattr(decision, 'request_id', '?'))}"
          f" för uppgift {result.task_id}; vald produkt {result.chosen.id}")
    return 0
