"""Lanseringen Q4: designer, Printify-produkter, listan, publicering och ordrar (LANSERING-Q4.md, D-070).

- **`pod designs`:** ritar de 20 designerna ur `products/q4/designs.toml`, en PNG per produkttyp och en
  förhandsvisning. Det kräver Pillow (`aie.pod.design`).
- **`pod prepare`:** körs i GitHub Actions, där `PRINTIFY_API_TOKEN` finns. För varje produkttyp:
  1. Typen hittas i katalogen. Tryckeriet väljs bland dem som levererar till både USA och EU, med den lägsta dyraste standardfrakten (`printify.read`).
  2. Designen laddas upp, och en **opublicerad** produkt skapas med titel, beskrivning, 13 taggar och de valda varianterna (`printify.draft`).
  3. Printifys verkliga baspris (`cost`) läses från produkten. Det lägsta priset med minst 30 % marginal enligt D-070 räknas fram och sätts på produkten. Finns inget sådant pris under `max_price` stryks produkten.
  4. Resultatet sparas i `products/q4/printify-products.json`.
- **`pod list`:** skriver `products/q4/LISTA.md` från resultatet, med en rad per produkt. Längst ner står raden där grundaren godkänner.
- **`pod publish --approved`:** publicerar bara produkterna i `LISTA.md` som inte är strukna, och bara om raden
  `GODKÄND – <namn>` finns. Varje produkt prövas mot testläget (D-070): marginalen och högst 20 aktiva annonser,
  räknat med dem som redan är publicerade i Printify. Publiceringen sker i Printify, som för produkten till den
  kopplade Etsy-butiken. Verktyget heter `printify.publish`.
- **`pod orders`:** läser nya ordrar från Printify och bokför dem i pilotens egen `prod`-databas i SEK, aldrig i SIM
  (ER-15):
  - kundens pris som intäkt
  - Printifys debitering (baspris, frakt och moms) som kostnad

  Samma order bokförs bara en gång (externt id).
"""
from __future__ import annotations

import base64
import json
import re
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .testmode import margin

AI_NOTE = ("Design made with the help of AI and finished by hand. Printed and shipped on demand by our production "
           "partner Printify.")
APPROVAL = re.compile(r"^GODKÄND\s*[–-]\s*(\S.*)$", re.MULTILINE)
ROW = re.compile(r"^\|\s*(~~)?\s*`(?P<key>[a-z0-9-]+/[a-z]+)`")


def load_designs(path: Path | str) -> list[dict]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("config_version") != 1:
        raise ValueError("designs.toml: config_version ska vara 1")
    return data["designs"]


def check_designs(designs: list[dict], rules: dict, blocklist: dict) -> dict[str, list[str]]:
    """Regler (D-067) för varje design: titel, 13 taggar, AI-upplysning, produktionspartner och spärrlistan."""
    from .rules import listing_problems

    out = {}
    for d in designs:
        listing = {"title": d["title"], "tags": d["tags"], "description": AI_NOTE, "production_partners": ["Printify"],
                   "design_text": " ".join(d["lines"])}
        problems = listing_problems(listing, rules, blocklist)
        if len(d["tags"]) != 13:
            problems.append(f"{len(d['tags'])} taggar; exakt 13 krävs")
        out[d["key"]] = problems
    return out


def render_all(designs: list[dict], out_dir: Path, sizes: dict[str, list[int]]) -> list[Path]:
    from .design import preview, render  # Pillow, bara här (D-070 punkt 8)

    files = []
    for d in designs:
        folder = out_dir / d["key"]
        spec = {"lines": d["lines"], "fonts": [d["font"]], "color": d["color"]}
        for product in d["products"]:
            files.append(render(spec, tuple(sizes[product]), folder / f"{product}.png"))
        files.append(preview(folder / f"{d['products'][0]}.png", folder / "preview.png"))
    return files


# --- Printify -----------------------------------------------------------------------------------

@dataclass
class Prepared:
    key: str  # "<design>/<produkttyp>"
    product_type: str
    title: str
    tags: list
    printify_id: str | None
    blueprint_id: int
    provider_id: int
    provider: str
    variants: list
    base_cost_minor: int | None
    shipping_us_minor: int
    shipping_eu_minor: int
    price_minor: int | None
    margin_bp: int | None
    profit_after_tax_minor: int | None
    struck: str | None  # skäl om produkten stryks
    pinterest: str


def eu_shipping(rows: list[dict], eu: list[str]) -> int | None:
    by_country = {}
    for r in rows:
        if r["first_item_minor"] is not None and r["currency"] == "USD":
            by_country[r["country"]] = max(by_country.get(r["country"], 0), r["first_item_minor"])
    fallback = by_country.get("REST_OF_THE_WORLD")
    values = [by_country.get(c, fallback) for c in eu]
    return None if any(v is None for v in values) else max(values)


def us_shipping(rows: list[dict]) -> int | None:
    values = [r["first_item_minor"] for r in rows if r["country"] == "US" and r["currency"] == "USD"
              and r["first_item_minor"] is not None]
    return max(values) if values else None


def choose_provider(reader, blueprint_id: int, eu: list[str], limit: int = 10) -> tuple[dict, int, int] | None:
    """Tryckeriet med lägst dyraste standardfrakt bland dem som levererar till både USA och EU."""
    best = None
    for p in reader.providers(blueprint_id)[:limit]:
        rows = reader.shipping(blueprint_id, p["id"])
        us, eu_max = us_shipping(rows), eu_shipping(rows, eu)
        if us is None or eu_max is None:
            continue
        if best is None or max(us, eu_max) < max(best[1], best[2]):
            best = (p, us, eu_max)
    return best


def pick_variants(variants: list[dict], colors: list[str], sizes: list[str]) -> list[dict]:
    chosen = []
    for v in variants:
        opts = v.get("options", {}) or {}
        title = v.get("title", "")
        color = opts.get("color") or title.split(" / ")[0]
        size = opts.get("size") or (title.split(" / ")[1] if " / " in title else "")
        if (not colors or color in colors) and (not sizes or size in sizes):
            chosen.append(v)
    return chosen


def placeholder_scale(variant: dict, position: str, image_size: tuple[int, int]) -> float:
    """Skala så att bilden ryms i tryckytan (Printify: scale 1 = tryckytans bredd)."""
    for ph in variant.get("placeholders", []):
        if ph.get("position") == position and ph.get("width") and ph.get("height"):
            w, h = image_size
            return round(min(1.0, (ph["height"] / ph["width"]) / (h / w)), 4)
    return 1.0


def best_price(base: int, us: int, eu: int, cfg: dict, tax_rate_bp: int, min_margin_bp: int) -> tuple[int, object] | None:
    """Lägsta pris (x,99 USD) med minst `min_margin_bp` enligt D-070, eller None om inget pris under taket räcker."""
    for dollars in range(cfg["min_price"] // 100, cfg["max_price"] // 100 + 1):
        price = dollars * 100 + 99
        if price > cfg["max_price"]:
            break
        u = margin(price, base, us, eu, tax_rate_bp)
        if u.margin_bp >= min_margin_bp:
            return price, u
    return None


def prepare(reader, drafter, shop_id: int, designs: list[dict], pod: dict, design_dir: Path) -> list[Prepared]:
    launch, tm = pod["launch"], pod["test_mode"]
    eu = launch["eu_countries"]
    blueprints = reader.blueprints()
    cache, results = {}, []
    for ptype, cfg in launch["products"].items():
        match = next((b for b in blueprints if b.get("id") == cfg.get("blueprint_id")), None) or next(
            (b for b in blueprints if cfg["search"].lower() in str(b.get("title", "")).lower()), None)
        if match is None:
            continue
        chosen = choose_provider(reader, match["id"], eu)
        if chosen is None:
            continue
        provider, us, eu_max = chosen
        variants = pick_variants(reader.variants(match["id"], provider["id"]), cfg.get("colors", []), cfg.get("sizes", []))
        cache[ptype] = (match, provider, us, eu_max, variants)
    for d in designs:
        for ptype in d["products"]:
            if ptype not in cache:
                continue
            match, provider, us, eu_max, variants = cache[ptype]
            key = f"{d['key']}/{ptype}"
            png = design_dir / d["key"] / f"{ptype}.png"
            item = Prepared(key, ptype, d["title"], d["tags"], None, match["id"], provider["id"], provider.get("title", ""),
                            [v["id"] for v in variants], None, us, eu_max, None, None, None, None, d.get("pinterest", ""))
            if not variants:
                item.struck = "inga varianter med valda färger och storlekar"
                results.append(item)
                continue
            image = drafter.upload_image_base64(f"{d['key']}-{ptype}.png", base64.b64encode(png.read_bytes()).decode("ascii"))
            size = _png_size(png)
            position = launch["products"][ptype].get("position", "front")
            product = {
                "title": d["title"], "description": f"{d.get('pinterest', '')}\n\n{AI_NOTE}", "tags": d["tags"],
                "blueprint_id": match["id"], "print_provider_id": provider["id"],
                "variants": [{"id": v["id"], "price": launch["products"][ptype]["max_price"], "is_enabled": True}
                             for v in variants],
                "print_areas": [{"variant_ids": [v["id"] for v in variants], "placeholders": [
                    {"position": position, "images": [{"id": image["id"], "x": 0.5, "y": 0.5,
                                                       "scale": placeholder_scale(variants[0], position, size),
                                                       "angle": 0}]}]}],
            }
            created = drafter.create_draft(shop_id, product)
            item.printify_id = created["id"]
            costs = [v["cost"] for v in drafter.get_product(shop_id, created["id"]).get("variants", [])
                     if v.get("is_enabled") and isinstance(v.get("cost"), int)]
            if not costs:
                item.struck = "Printify gav inget baspris"
                results.append(item)
                continue
            item.base_cost_minor = max(costs)
            found = best_price(item.base_cost_minor, us, eu_max, launch["products"][ptype], tm["tax_rate_bp"],
                               tm["min_margin_bp"])
            if found is None:
                cap = launch["products"][ptype]["max_price"]
                best = margin(cap, item.base_cost_minor, us, eu_max, tm["tax_rate_bp"])
                item.price_minor, item.margin_bp, item.profit_after_tax_minor = cap, best.margin_bp, best.profit_after_tax
                item.struck = f"under 30 % även vid takpriset {cap / 100:.2f} USD ({best.margin_bp / 100:.1f} %)"
            else:
                price, u = found
                item.price_minor, item.margin_bp, item.profit_after_tax_minor = price, u.margin_bp, u.profit_after_tax
                drafter.set_price(shop_id, created["id"], [{"id": v["id"], "price": price} for v in variants])
            results.append(item)
    return results


def _png_size(path: Path) -> tuple[int, int]:
    data = Path(path).read_bytes()[16:24]
    return int.from_bytes(data[:4], "big"), int.from_bytes(data[4:], "big")


def save(results: list[Prepared], path: Path) -> Path:
    path.write_text(json.dumps({"prepared_on": datetime.now(UTC).date().isoformat(),
                                "products": [asdict(r) for r in results]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --- LISTA.md ---------------------------------------------------------------------------------

def write_list(prepared: dict, designs: list[dict], usd_sek: float, out: Path) -> Path:
    by_key = {d["key"]: d for d in designs}
    rows = ["# Produkter för lanseringen Q4 (LISTA)", "",
            f"Förberedda i Printify {prepared['prepared_on']}, **opublicerade**. Testläget gäller (D-070): minst 30 % marginal "
            "per såld vara efter Printifys baspris, den dyraste frakten till USA eller EU, Etsys avgifter och 40 % skatt "
            f"på vinsten. Priset inkluderar frakten. Kronor med kursen {usd_sek} SEK/USD (antagande, uppdatera vid behov).", "",
            "Stryk en produkt genom att sätta `~~` först och sist på raden. Strukna och för låga rader publiceras aldrig.", "",
            "| Produkt | Bild | Typ | Kostnad (bas + frakt) | Pris | Marginal | Taggar | Pinterest |",
            "|---|---|---|---|---|---|---|---|"]
    for p in prepared["products"]:
        d = by_key.get(p["key"].split("/")[0], {})
        cost = (p["base_cost_minor"] or 0) + max(p["shipping_us_minor"], p["shipping_eu_minor"])
        if p["price_minor"] and p["margin_bp"] is not None:
            kr = p["profit_after_tax_minor"] / 100 * usd_sek
            m = f"{kr:.0f} kr ({p['margin_bp'] / 100:.1f} %)"
        else:
            m = "–"
        pin_title = d.get("title", p["title"]).split(",")[0]
        pinterest = f"**{pin_title}**: {p['pinterest']} Link: Etsy listing."
        line = (f"| `{p['key']}` | ![{p['key']}]({p['key'].split('/')[0]}/preview.png) | {p['product_type']} | "
                f"{cost / 100:.2f} USD ({cost / 100 * usd_sek:.0f} kr) | "
                f"{(p['price_minor'] or 0) / 100:.2f} USD ({(p['price_minor'] or 0) / 100 * usd_sek:.0f} kr) | {m} | "
                f"{', '.join(p['tags'])} | {pinterest} |")
        if p["struck"]:
            line = f"| ~~`{p['key']}`~~ | – | {p['product_type']} | {cost / 100:.2f} USD | – | {m} | **STRUKEN:** {p['struck']} | – |"
        rows.append(line)
    rows += ["", "Godkänn genom att skriva GODKÄND – namn", ""]
    out.write_text("\n".join(rows), encoding="utf-8")
    return out


def approved_keys(text: str) -> tuple[str | None, list[str]]:
    """(vem som godkänt, ostrukna produkter) ur LISTA.md. Utan raden GODKÄND är listan inte godkänd."""
    who = APPROVAL.search(text)
    keys = []
    for line in text.splitlines():
        m = ROW.match(line)
        if m and not m.group(1) and "STRUKEN" not in line and not line.strip().startswith("| ~~"):
            keys.append(m.group("key"))
    return (who.group(1).strip() if who else None), keys


def publish(text: str, prepared: dict, publisher, test_mode, already_published: int) -> list[str]:
    """Publicerar de godkända, ostrukna produkterna i testläget. Returnerar en rad per produkt."""
    who, keys = approved_keys(text)
    if who is None:
        raise PermissionError("LISTA.md saknar raden 'GODKÄND – namn'; inget publiceras")
    by_key = {p["key"]: p for p in prepared["products"]}
    out, active = [], already_published
    for key in keys:
        p = by_key.get(key)
        if p is None or not p["printify_id"] or p["struck"]:
            out.append(f"{key}: hoppas över (saknas, eller struken av kalkylen)")
            continue
        data = {"price_minor": p["price_minor"], "currency": "USD",
                "test_mode": {"base_cost_minor": p["base_cost_minor"], "shipping_us_minor": p["shipping_us_minor"],
                              "shipping_eu_minor": p["shipping_eu_minor"]}}
        problems = test_mode.problems(data, active)
        if problems:
            out.append(f"{key}: publiceras inte: {'; '.join(problems)}")
            continue
        publisher(p["printify_id"])
        active += 1
        out.append(f"{key}: publicerad (godkänd av {who})")
    return out


# --- Ordrar -------------------------------------------------------------------------------------

def book_orders(system, founder: str, orders: list[dict], prepared: dict, usd_sek: float) -> dict:
    """Bokför Printify-ordrar i pilotens ledger (SEK). Samma order bokförs en gång."""
    from decimal import ROUND_HALF_UP, Decimal

    from ..ledger import Approval, EntryDraft, EntryType, Status

    if system.currency == "SIM":
        raise ValueError("riktiga ordrar bokförs aldrig i en SIM-databas (ER-15)")
    initiative_of = {p["printify_id"]: f"pod-{p['key'].replace('/', '-')}" for p in prepared.get("products", [])
                     if p.get("printify_id")}
    rate = Decimal(str(usd_sek))
    sek = lambda cents: int((Decimal(cents) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    known = {e.external_id for e in system.ledger.entries(system.currency) if e.external_id}
    result = {"orders": 0, "revenue_minor": 0, "cost_minor": 0, "skipped": 0}
    for order in orders:
        oid = str(order.get("id"))
        day = str(order.get("created_at", ""))[:10] or datetime.now(UTC).date().isoformat()
        lines = order.get("line_items", [])
        initiative = next((initiative_of.get(li.get("product_id")) for li in lines if li.get("product_id") in initiative_of),
                          "pod-okand-produkt")
        revenue = sum(int((li.get("metadata") or {}).get("price") or 0) * int(li.get("quantity") or 1) for li in lines)
        cost = int(order.get("total_price") or 0) + int(order.get("total_shipping") or 0) + int(order.get("total_tax") or 0)
        posts = [("sale", EntryType.REVENUE, revenue, Status.PENDING), ("printify", EntryType.COST, cost, Status.SETTLED)]
        new = False
        for suffix, kind, cents, status in posts:
            external_id = f"printify-order:{oid}:{suffix}"
            if external_id in known or not cents:
                continue
            system.ledger.record(founder, EntryDraft(
                external_id, "research", sek(cents), system.currency, kind, initiative, Approval.APPROVED,
                (f"external:printify-order/{oid}", f"external:kurs-usd-sek/{rate}", "decision:D-070"),
                external_id=external_id, status=status,
                note=f"Printify-order {oid} ({'kundens pris, väntar på Etsys utbetalning' if suffix == 'sale' else 'Printifys debitering'})",
                occurred_on=day))
            known.add(external_id)
            new = True
            result["revenue_minor" if suffix == "sale" else "cost_minor"] += sek(cents)
        result["orders" if new else "skipped"] += 1
    return result
