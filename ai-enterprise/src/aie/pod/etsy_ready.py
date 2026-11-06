"""En opublicerad Printify-produkt per design, redo för Etsy (testläget, LANSERING-Q4.md).

För varje `products/q4/<nyckel>/meta.json`:
1. **Butiken:** den som är kopplad till Etsy, annars den första.
2. **Tryckeriet:** för produkttypen i meta.json väljs det med lägst frakt till USA bland dem som skickar till både USA och EU.
3. **Priset:** lägsta x,99 USD med minst 30 % marginal enligt testläget:
   - **Grund:** priset inkluderar frakten till USA.
   - **Etsys avgifter:** 6,5 % + 3 % + 0,25 USD + 0,20 USD.
   - **Skatt:** 30 % av vinsten.

   Över taket (`MAX_PRICE`) stryks produkten.
4. **Produkten:** bilden laddas upp och en **opublicerad** produkt skapas med engelsk titel, beskrivning och 13 taggar. Finns
   redan ett utkast för designen och typen (`printify-products.json`, från en tidigare körning) uppdateras det
   i stället, så att inga dubbletter uppstår.
5. **meta.json** får produkt-id, kostnad, pris och marginal, eller skälet till att produkten ströks eller felet.

Varje anrop görs högst två gånger. Ett fel hoppar över designen och noteras.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from .http import ApiError
from .launch import choose_provider, load_designs, pick_variants, placeholder_scale

ENDING = "Design created with the help of AI. Produced and shipped by our production partner Printify."
MAX_PRICE = {"tee": 4_500, "hoodie": 6_999, "mug": 3_499, "poster": 4_500}
_NOUN = {"tee": "Shirt", "hoodie": "Hoodie", "mug": "Mug", "poster": "Poster"}
_OTHER = r"Coffee Cup|T-Shirt|Shirt|Tee|Hoodie|Crewneck|Mug|Cup|Poster|Top"
_FILLER = {"tee": ["unisex t-shirt", "graphic tee", "gift idea"], "hoodie": ["unisex hoodie", "cozy hoodie", "gift idea"],
           "mug": ["coffee mug", "ceramic mug", "gift idea"], "poster": ["wall art", "art print", "gift idea"]}


def unit(price: int, base: int, shipping_us: int) -> dict:
    """Kalkyl per såld vara i cent: avgifter 6,5 % + 3 % + 25 + 20, skatt 30 % av vinsten."""
    fees = -(-price * 650 // 10_000) + -(-price * 300 // 10_000) + 25 + 20
    profit = price - fees - base - shipping_us
    after = profit - max(0, -(-profit * 3_000 // 10_000))
    return {"fees": fees, "profit_before_tax": profit, "profit_after_tax": after,
            "margin_bp": after * 10_000 // price if price else 0}


def price_for(base: int, shipping_us: int, cap: int) -> tuple[int, dict] | None:
    for dollars in range(5, cap // 100 + 1):
        price = dollars * 100 + 99
        if price > cap:
            break
        u = unit(price, base, shipping_us)
        if u["margin_bp"] >= 3_000:
            return price, u
    return None


def adapt(title: str, tags: list[str], ptype: str) -> tuple[str, list[str]]:
    noun = _NOUN[ptype]
    new_title = re.sub(rf"\b({_OTHER})\b", noun, title)
    out = []
    for tag in tags:
        t = re.sub(rf"\b({_OTHER.lower()})\b", noun.lower(), tag)
        if len(t) <= 20 and t not in out:
            out.append(t)
    for filler in _FILLER[ptype]:
        if len(out) < 13 and filler not in out:
            out.append(filler)
    return new_title, out[:13]


def _twice(fn, *args):
    """Klienten görs med `retries=1`: varje anrop högst två gånger vid 429/5xx; andra fel stoppar designen."""
    return fn(*args)


def choose_shop(shops: list[dict]) -> dict:
    return next((s for s in shops if str(s.get("sales_channel", "")).lower() == "etsy"), shops[0])


def run(reader, drafter, pod: dict, folder: Path) -> dict:
    designs = {d["key"]: d for d in load_designs(folder / "designs.toml")}
    old_path = folder / "printify-products.json"
    old = {p["key"]: p for p in json.loads(old_path.read_text(encoding="utf-8"))["products"]} if old_path.is_file() else {}
    shop = choose_shop(_twice(reader.shops))
    shop_id = shop["id"]
    eu = pod["launch"]["eu_countries"]
    blueprints = _twice(reader.blueprints)
    cache: dict = {}
    summary = {"shop_id": shop_id, "shop": shop.get("title"), "sales_channel": shop.get("sales_channel"),
               "created": 0, "updated": 0, "struck": 0, "errors": 0, "margins_bp": []}
    for meta_path in sorted(folder.glob("*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        design, ptype = designs.get(meta["key"]), meta["product_type"]
        for k in ("struck", "error"):
            meta.pop(k, None)
        try:
            cfg = pod["launch"]["products"][ptype]
            if ptype not in cache:
                bp = next((b for b in blueprints if b.get("id") == cfg.get("blueprint_id")), None) or next(
                    (b for b in blueprints if cfg["search"].lower() in str(b.get("title", "")).lower()), None)
                chosen = _twice(choose_provider, reader, bp["id"], eu) if bp else None
                variants = pick_variants(_twice(reader.variants, bp["id"], chosen[0]["id"]),
                                         cfg.get("colors", []), cfg.get("sizes", [])) if chosen else []
                cache[ptype] = (bp, chosen, variants)
            bp, chosen, variants = cache[ptype]
            if not chosen or not variants:
                raise ApiError(f"inget tryckeri för {ptype} skickar till både USA och EU med valda varianter")
            provider, ship_us, ship_eu = chosen
            title, tags = adapt(design["title"], design["tags"], ptype)
            description = f"{design.get('pinterest', '')}\n\n{ENDING}"
            previous = old.get(f"{meta['key']}/{ptype}")
            if previous and previous.get("printify_id"):
                product_id = previous["printify_id"]
                ship_us = previous["shipping_us_minor"]
                _twice(drafter.update, shop_id, product_id, {"title": title, "description": description, "tags": tags})
                variant_ids = previous["variants"]
                summary["updated"] += 1
            else:
                png = meta_path.parent / "design.png"
                image = _twice(drafter.upload_image_base64, f"{meta['key']}-{ptype}.png",
                               base64.b64encode(png.read_bytes()).decode("ascii"))
                size = (meta["size_px"][0], meta["size_px"][1])
                variant_ids = [v["id"] for v in variants]
                product = {"title": title, "description": description, "tags": tags, "blueprint_id": bp["id"],
                           "print_provider_id": provider["id"],
                           "variants": [{"id": v, "price": MAX_PRICE[ptype], "is_enabled": True} for v in variant_ids],
                           "print_areas": [{"variant_ids": variant_ids, "placeholders": [
                               {"position": cfg.get("position", "front"),
                                "images": [{"id": image["id"], "x": 0.5, "y": 0.5,
                                            "scale": placeholder_scale(variants[0], cfg.get("position", "front"), size),
                                            "angle": 0}]}]}]}
                product_id = _twice(drafter.create_draft, shop_id, product)["id"]
                summary["created"] += 1
            costs = [v["cost"] for v in _twice(drafter.get_product, shop_id, product_id).get("variants", [])
                     if v.get("is_enabled") and isinstance(v.get("cost"), int)]
            base = max(costs)
            meta.update({"printify_product_id": product_id, "shop_id": shop_id, "provider": provider.get("title"),
                         "title": title, "tags": tags, "base_cost_usd_cents": base, "shipping_us_usd_cents": ship_us})
            found = price_for(base, ship_us, MAX_PRICE[ptype])
            if found is None:
                u = unit(MAX_PRICE[ptype], base, ship_us)
                meta.update({"price_usd_cents": None, "margin_pct": round(u["margin_bp"] / 100, 1),
                             "struck": f"over {MAX_PRICE[ptype] / 100:.2f} USD needed for 30 % margin"})
                summary["struck"] += 1
            else:
                price, u = found
                _twice(drafter.set_price, shop_id, product_id, [{"id": v, "price": price} for v in variant_ids])
                meta.update({"price_usd_cents": price, "cost_usd_cents": base + ship_us,
                             "fees_usd_cents": u["fees"], "profit_after_tax_usd_cents": u["profit_after_tax"],
                             "margin_pct": round(u["margin_bp"] / 100, 1)})
                summary["margins_bp"].append(u["margin_bp"])
        except (ApiError, KeyError, ValueError, StopIteration, TypeError) as exc:
            meta["error"] = f"{type(exc).__name__}: {exc}"[:300]
            summary["errors"] += 1
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
