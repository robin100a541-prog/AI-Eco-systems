"""`python -m aie pod designs|prepare|list|publish|orders` (LANSERING-Q4.md, D-070).

    python -m aie pod designs                          # ritar products/q4/<design>/*.png (Pillow)
    python -m aie pod prepare --as yorgo               # i GitHub Actions: opublicerade produkter i Printify
    python -m aie pod list                             # skriver products/q4/LISTA.md
    python -m aie pod publish --approved --as yorgo    # publicerar det godkända (högst 20, testläget)
    python -m aie pod orders --as yorgo                # bokför nya Printify-ordrar i pilotens ledger (SEK)

`prepare`, `publish` och `orders` kräver `PRINTIFY_API_TOKEN`. Nyckeln läses bara från miljön och skrivs aldrig ut.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import runtime
from ..authorization import PermissionDenied
from ..config import ConfigError
from . import launch
from .http import ApiError
from .printify import PrintifyClient, PrintifyDrafter, PrintifyPublisher, PrintifyReader, load_pod_config

Q4 = Path("products/q4")
PREPARED = "printify-products.json"
AGENT_READ, AGENT_WRITE = "res-1", "lead-1"


def pod(config_dir: Path, action: str, founder: str | None = None, approved: bool = False, folder: Path = Q4) -> int:
    try:
        cfg = load_pod_config(config_dir)
        designs = launch.load_designs(folder / "designs.toml")
        if action == "designs":
            from .rules import load_blocklist

            problems = {k: v for k, v in launch.check_designs(designs, cfg["etsy"]["listing_rules"],
                                                              load_blocklist(config_dir)).items() if v}
            if problems:
                for key, p in problems.items():
                    print(f"STOPPAD {key}: {'; '.join(p)}", file=sys.stderr)
                return 1
            sizes = {k: v["print_px"] for k, v in cfg["launch"]["products"].items()}
            files = launch.render_all(designs, folder, sizes)
            print(f"{len(designs)} designer, {len(files)} filer i {folder}")
            return 0
        if action == "list":
            prepared = json.loads((folder / PREPARED).read_text(encoding="utf-8"))
            path = launch.write_list(prepared, designs, cfg["launch"]["usd_sek"], folder / "LISTA.md")
            ok = [p for p in prepared["products"] if not p["struck"]]
            print(f"{len(prepared['products'])} produkter i {path}, {len(ok)} med minst 30 % marginal")
            return 0
        if action == "orders":
            return _orders(config_dir, cfg, founder, folder)
        return _with_system(config_dir, cfg, action, founder, approved, designs, folder)
    except (ConfigError, ValueError, OSError, ApiError, PermissionError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1


def _with_system(config_dir, cfg, action, founder, approved, designs, folder) -> int:
    from ..simulation.agents import ensure_org
    from ..system import build_system
    from .testmode import TestMode

    config = runtime._load(config_dir, console=False)
    with runtime._open(config) as db:
        system = build_system(config, db, config_dir)
        if founder:
            ensure_org(system.registry, founder)
        client = PrintifyClient.from_env()
        reader = PrintifyReader(system.engine, system.audit, AGENT_READ, client)
        shop = cfg["launch"].get("shop_id") or reader.shops()[0]["id"]
        try:
            if action == "prepare":
                drafter = PrintifyDrafter(system.engine, system.audit, AGENT_WRITE, client, cfg)
                old_path = folder / PREPARED
                old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.is_file() else {"products": []}
                existing = {p["key"]: p for p in old["products"]}
                results = launch.prepare(reader, drafter, shop, designs, cfg, folder, existing)
                launch.save(results, folder / PREPARED)
                ok = [r for r in results if not r.struck]
                print(f"{len(results)} opublicerade produkter i Printify, {len(ok)} med minst 30 % marginal. "
                      f"Sparat i {folder / PREPARED}.")
                for r in results:
                    print(f"  {r.key}: {r.provider}, baspris {r.base_cost_minor}, frakt USA {r.shipping_us_minor} "
                          f"EU {r.shipping_eu_minor}, pris {r.price_minor}, marginal "
                          f"{'-' if r.margin_bp is None else r.margin_bp / 100}% {('STRUKEN: ' + r.struck) if r.struck else ''}")
                return 0
            if not approved:
                print("FEL: publish kräver --approved (och raden GODKÄND i LISTA.md)", file=sys.stderr)
                return 1
            text = (folder / "LISTA.md").read_text(encoding="utf-8")
            prepared = json.loads((folder / PREPARED).read_text(encoding="utf-8"))
            published = sum(1 for p in reader.products(shop) if p.get("visible") and p.get("external"))
            publisher = PrintifyPublisher(system.engine, system.audit, AGENT_WRITE, client, shop)
            for line in launch.publish(text, prepared, publisher, TestMode(cfg), published):
                print(line)
            return 0
        except PermissionDenied as exc:
            print(f"FEL: {exc}", file=sys.stderr)
            return 1


def _orders(config_dir, cfg, founder, folder) -> int:
    from ..pilot.cli import PILOT_ROOT, _pilot_system
    from ..simulation.agents import ensure_org
    from ..system import build_system

    if not founder:
        raise ValueError("orders kräver --as <grundare>")
    pconf_dir, config = _pilot_system(config_dir, PILOT_ROOT)
    with runtime._open(config) as db:
        system = build_system(config, db, pconf_dir)
        ensure_org(system.registry, founder)
        reader = PrintifyReader(system.engine, system.audit, AGENT_READ, PrintifyClient.from_env())
        shop = cfg["launch"].get("shop_id") or reader.shops()[0]["id"]
        prepared_path = folder / PREPARED
        prepared = json.loads(prepared_path.read_text(encoding="utf-8")) if prepared_path.is_file() else {}
        orders = reader.orders(shop)
        result = launch.book_orders(system, founder, orders, prepared, cfg["launch"]["usd_sek"])
        print(f"Ordrar från Printify: {len(orders)} lästa, {result['orders']} nya bokförda, {result['skipped']} redan bokförda. "
              f"Intäkt {result['revenue_minor'] / 100:.2f} SEK (väntar på Etsy), kostnad {result['cost_minor'] / 100:.2f} SEK.")
        return 0
