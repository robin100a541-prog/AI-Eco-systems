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


PILOT_ROOT = Path("data-pilot")


def _pilot_system(config_dir: Path, root: Path):
    """(config, db-kontext) för pilotens egen prod-databas."""
    from .live import pilot_config

    pconf_dir = pilot_config(config_dir, root)
    return pconf_dir, runtime._load(pconf_dir, console=False)


def live(config_dir: Path, action: str, founder: str | None, product: Path | None, request_id: int | None,
         root: Path = PILOT_ROOT, today: str | None = None) -> int:
    from datetime import UTC, datetime

    from ..governance.cli import build
    from ..system import build_system
    from .live import PilotError, approve, approval, check_stops, initiative_for, load_idea, prepare, stop_advice

    try:
        pconf_dir, config = _pilot_system(config_dir, root)
        if founder is not None and founder.lower() not in config.system.founders:
            raise PilotError(f"{founder!r} är ingen grundare")
        with runtime._open(config) as db:
            gov = build(config, db, pconf_dir)
            if action == "prepare":
                text, request = prepare(gov, config.risk, founder.lower(), product)
                print(text, end="")
            elif action == "approve":
                req = approve(gov, build_system(config, db, pconf_dir), founder, request_id)
                print(f"Förfrågan #{req.request_id}: {req.status.value} (godkänd av {', '.join(req.approvals)})")
            else:
                system = build_system(config, db, pconf_dir)
                initiative = initiative_for(load_idea(product)) if product else None
                print(f"Pilotens databas: miljö {config.system.environment}, valuta {system.currency} (aldrig SIM)")
                pending = gov.queue.pending()
                print(f"Väntande förfrågningar: {len(pending)}")
                if initiative:
                    found = approval(db, initiative)
                    since = found[1] if found else None
                    print(f"Godkänd: {since or 'nej'}")
                    reasons = check_stops(system, founder or "robin", initiative, since,
                                          today or datetime.now(UTC).date().isoformat())
                    print(stop_advice(reasons))
    except (ConfigError, PilotError, ValueError, PermissionError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    return 0


def import_platform_sales(config_dir: Path, founder: str, csv_path: Path, product: Path, usd_sek: float,
                   reported_net_usd: float | None, root: Path = PILOT_ROOT, today: str | None = None) -> int:
    from datetime import UTC, datetime

    from ..system import build_system
    from .live import PilotError, approval, check_stops, import_sales, initiative_for, load_idea, stop_advice

    try:
        pconf_dir, config = _pilot_system(config_dir, root)
        founder = founder.lower()
        if founder not in config.system.founders:
            raise PilotError(f"{founder!r} är ingen grundare")
        initiative = initiative_for(load_idea(product))
        with runtime._open(config) as db:
            system = build_system(config, db, pconf_dir)
            result = import_sales(system, founder, initiative, csv_path.read_text(encoding="utf-8"), usd_sek,
                                  reported_net_usd)
            found = approval(db, initiative)
            since = found[1] if found else None
            reasons = check_stops(system, founder, initiative, since, today or datetime.now(UTC).date().isoformat())
            reserved = system.tax.reserved_minor(system.currency)
    except (ConfigError, PilotError, ValueError, PermissionError, OSError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    print(f"Importerat {result.sales} försäljningar ({result.refunds} återbetalda, {result.duplicates} dubbletter "
          f"hoppades över). Brutto {result.gross_minor / 100:.2f} kr, avgifter {result.fees_minor / 100:.2f} kr, "
          f"återbetalt {result.refunds_minor / 100:.2f} kr, netto {result.net_minor / 100:.2f} kr. "
          f"Skattereserv totalt {reserved / 100:.2f} kr.")
    if result.mismatch:
        print(f"AVSTÄMNING STÄMMER INTE: {result.mismatch}. Incident #{result.incident_id} är öppnad.")
    print(stop_advice(reasons))
    return 2 if result.mismatch else 0
