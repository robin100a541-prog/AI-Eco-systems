"""LISTA.md och publicering (testläget, LANSERING-Q4.md).

- **`write(folder)`:** skriver `LISTA.md` från `products/q4/*/meta.json`, en rad per produkt. Längst ner står raden
  "Godkänn genom att skriva GODKÄND – namn". En rad stryks genom att sättas inom `~~`.
- **`publish(text, publisher)`:** publicerar produkterna i listan, men bara under tre villkor:
  - listan har en rad `GODKÄND – <namn>`
  - raden är inte överstruken
  - högst `limit` totalt, normalt 20

  `publisher(product_id)` gör anropet till Printifys publish-endpoint (`PrintifyPublisher`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LIMIT = 20
APPROVAL = re.compile(r"^\s*GODKÄND\s*[–-]\s*(\S.*)$", re.MULTILINE)
PRODUCT_ID = re.compile(r"`([0-9a-f]{24})`")


def _usd(cents) -> str:
    return "–" if cents is None else f"{cents / 100:.2f} USD"


def pinterest(meta: dict) -> str:
    parts = [p.strip() for p in meta["title"].split(",")]
    sentence = " and ".join(p.lower() for p in parts[1:3]) if len(parts) > 2 else "an original typography design"
    return f"**{parts[0]}**: {sentence[0].upper() + sentence[1:]}, printed on demand and shipped to your door."


def write(folder: Path | str) -> Path:
    folder = Path(folder)
    rows = ["# Produkter för lanseringen Q4 (LISTA)", "",
            "Opublicerade produkter i Printify. Priset inkluderar frakt till USA. Marginalen är vinst efter Etsys avgifter "
            "(6,5 % + 3 % + 0,25 + 0,20 USD) och 30 % skatt. Stryk en produkt genom att sätta `~~` runt raden.", "",
            "| Produkt | Bild | Typ | Kostnad | Pris | Marginal | Taggar | Pinterest |", "|---|---|---|---|---|---|---|---|"]
    for path in sorted(folder.glob("*/meta.json")):
        m = json.loads(path.read_text(encoding="utf-8"))
        if not m.get("printify_product_id") or m.get("struck") or (m.get("margin_pct") or 0) < 30:
            continue  # bara produkter med minst 30 % marginal
        if sum(1 for r in rows if r.startswith("| ") and "`" in r) >= LIMIT:
            break  # högst 20
        row = (f"| {m['key']} `{m['printify_product_id']}` | [![{m['key']}]({m['key']}/design.png)]({m['key']}/design.png) | "
               f"{m['product_type']} | {_usd(m.get('cost_usd_cents'))} | {_usd(m.get('price_usd_cents'))} | "
               f"{_usd(m.get('profit_after_tax_usd_cents'))} ({m.get('margin_pct')} %) | {', '.join(m.get('tags', []))} | "
               f"{pinterest(m)} |")
        rows.append(f"~~{row}~~" if m.get("struck") else row)
    rows += ["", "Godkänn genom att skriva GODKÄND – namn", ""]
    out = folder / "LISTA.md"
    out.write_text("\n".join(rows), encoding="utf-8")
    return out


def approved(text: str) -> tuple[str | None, list[str]]:
    """(vem som godkänt, produkt-id i ordning) för rader som inte är överstrukna."""
    who = APPROVAL.search(text)
    ids = []
    for line in text.splitlines():
        if line.lstrip().startswith("|") or line.lstrip().startswith("~~|"):
            found = PRODUCT_ID.search(line)
            if found and "~~" not in line:
                ids.append(found.group(1))
    return (who.group(1).strip() if who else None), ids


def publish(text: str, publisher, limit: int = LIMIT) -> tuple[list[str], list[str]]:
    """Publicerar godkända rader. Returnerar (publicerade id, fel). Utan GODKÄND publiceras inget."""
    who, ids = approved(text)
    if who is None:
        return [], ["LISTA.md saknar raden 'GODKÄND – namn'; inget publicerades"]
    done, errors = [], []
    for product_id in ids:
        if len(done) >= limit:
            errors.append(f"{product_id}: inte publicerad; gränsen {limit} är nådd")
            continue
        try:
            publisher(product_id)
            done.append(product_id)
        except Exception as exc:  # noqa: BLE001 — ett fel stoppar inte resten, och skrivs ut
            errors.append(f"{product_id}: {type(exc).__name__}: {exc}"[:300])
    return done, errors
