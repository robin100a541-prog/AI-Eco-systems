"""`python -m aie printify shops|blueprints|snapshot|catalog` (arbetsorder 04, D-065).

    python -m aie printify shops --agent res-1
    python -m aie printify blueprints --agent res-1 --find mug
    python -m aie printify snapshot --agent res-1 --blueprint 68 --provider 1
    python -m aie printify catalog --agent res-1 --as yorgo --out reports/printify

Alla kommandon läser och kräver verktyget `printify.read`. Verktyget går genom hela systemets Authorization
Engine, så nödstoppet och skyddat läge stoppar det. Nyckeln läses från `PRINTIFY_API_TOKEN` och skrivs aldrig
ut. `catalog` är den dagliga körningen. Den sparar katalogens storlek och en ögonblicksbild (varianter och
standardfrakt per land) för produkterna i `catalog_watch` och för sökorden i `q4_search` i
`config/pod.toml`, som JSON i `--out`. `--as` registrerar organisationen i en tom databas.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .. import runtime
from ..authorization import PermissionDenied
from ..config import ConfigError
from .http import ApiError
from .printify import PrintifyClient, PrintifyReader, load_pod_config

MAX_SNAPSHOTS = 12  # katalogens gräns är 100 anrop per minut; varje ögonblicksbild kostar 2 anrop


def printify(config_dir: Path, action: str, agent: str, founder: str | None = None, find: str | None = None,
             blueprint: int | None = None, provider: int | None = None, out: Path | None = None) -> int:
    from ..simulation.agents import ensure_org
    from ..system import build_system

    try:
        config = runtime._load(config_dir, console=False)
        pod = load_pod_config(config_dir)
        if not pod.get("printify", {}).get("read_enabled", False):
            print("FEL: printify.read är avstängt i config/pod.toml", file=sys.stderr)
            return 1
        with runtime._open(config) as db:
            try:
                system = build_system(config, db, config_dir)
            except ConfigError as exc:
                raise runtime.StartupError(f"FEL: {exc}") from exc
            if founder:
                ensure_org(system.registry, founder)
            try:
                reader = PrintifyReader(system.engine, system.audit, agent, PrintifyClient.from_env())
                if action == "shops":
                    for s in reader.shops():
                        print(f"butik {s.get('id')}: {s.get('title')} ({s.get('sales_channel')})")
                    return 0
                if action == "blueprints":
                    for b in _matching(reader.blueprints(), find):
                        print(f"{b.get('id'):>5} {b.get('title')} — {b.get('brand')} {b.get('model')}")
                    return 0
                if action == "snapshot":
                    countries = pod["printify"].get("countries", ["US"])
                    providers = [provider] if provider else [p["id"] for p in reader.providers(blueprint)[:3]]
                    print(json.dumps([reader.snapshot(blueprint, p, countries) for p in providers],
                                     ensure_ascii=False, indent=2))
                    return 0
                result = catalog(reader, pod)
                target = Path(out or "reports/printify")
                target.mkdir(parents=True, exist_ok=True)
                path = target / f"printify-catalog-{result['read_on']}.json"
                path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Katalog: {result['blueprints']} produkter, {len(result['snapshots'])} ögonblicksbilder, "
                      f"{result['calls']} anrop. Sparad i {path}.")
                return 0
            except (ApiError, PermissionDenied, ValueError) as exc:
                print(f"FEL: {exc}", file=sys.stderr)
                return 1
    except runtime.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1


def catalog(reader: PrintifyReader, pod: dict) -> dict:
    """Den dagliga läsningen. Bara läsande anrop, högst `MAX_SNAPSHOTS` ögonblicksbilder."""
    cfg = pod["printify"]
    blueprints = reader.blueprints()
    wanted = [(w["blueprint"], w.get("provider")) for w in cfg.get("catalog_watch", [])]
    for term in cfg.get("q4_search", []):
        for b in _matching(blueprints, term)[:1]:
            wanted.append((b["id"], None))
    snapshots, errors = [], []
    for blueprint_id, provider_id in list(dict.fromkeys(wanted))[:MAX_SNAPSHOTS]:
        try:
            if provider_id is None:
                providers = reader.providers(blueprint_id)
                if not providers:
                    continue
                provider_id = providers[0]["id"]
            snap = reader.snapshot(blueprint_id, provider_id, cfg.get("countries", ["US"]))
            title = next((b.get("title") for b in blueprints if b.get("id") == blueprint_id), None)
            snapshots.append({"title": title, **snap})
        except ApiError as exc:
            errors.append(f"{blueprint_id}: {exc}")
    return {"read_on": datetime.now(UTC).date().isoformat(), "source": "api.printify.com (printify.read)",
            "blueprints": len(blueprints), "snapshots": snapshots, "errors": errors,
            "calls": reader._client.calls,
            "note": "Katalogens varianter saknar pris; cost_minor är None tills en produkt finns i butiken (D-069)."}


def _matching(blueprints: list[dict], find: str | None) -> list[dict]:
    if not find:
        return blueprints
    terms = find.lower().split()
    return [b for b in blueprints if all(t in f"{b.get('title', '')} {b.get('description', '')}".lower() for t in terms)]
