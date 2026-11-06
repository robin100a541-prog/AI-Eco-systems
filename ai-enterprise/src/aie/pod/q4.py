"""Q4-idéer: motiv, kalkyl och spärren "simulera före start" (arbetsorder 04, D-066).

`python -m aie q4 --as <grundare>` gör följande för varje idé i `products/q4/ideas.toml`:

1. **Regler** (`aie.pod.rules`): titel, taggar, AI-upplysning, produktionspartner och spärrlistan. En idé som bryter mot dem stoppas och får ingen design.
2. **Design:** en egen PNG i tryckstorlek, och en liten förhandsvisning (`aie.pod.designs`).
3. **Kalkyl per order** (`aie.pod.costs`), i två varianter:
   - **normal:** antagna kostnader och inga Offsite Ads
   - **pessimistisk:** baspris + 20 %, frakt + 30 % och en fjärdedel av ordren via Offsite Ads

   Har `--catalog` en ögonblicksbild från `printify.read`, används Printifys verkliga frakt och tryckyta.
4. **Spärren (D-058):** `assess_initiative` kör det normala, det pessimistiska (efterfrågan × 0,25) och nollförsäljningsscenariot. Det sker i en tillfällig databas, med Etsy ur registret som plattform. Idén blir "redo" bara om spärren säger det.
5. **Utkast:** `products/q4/<idé>/README.md` och `products/q4/REPORT.md` med rangordning. Inget publiceras.
"""
from __future__ import annotations

import json
import tempfile
import tomllib
from dataclasses import replace
from pathlib import Path

from .costs import unit
from .designs import render_pattern, render_text, write_png
from .printify import load_pod_config
from .rules import listing_problems, load_blocklist

AI_TEXT = "AI-assisted design: made with the help of AI and checked by hand. Original artwork, produced by our print partner Printify."
PREVIEW_W = 600


def load_ideas(path: Path | str) -> dict:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("config_version") != 1:
        raise ValueError("ideas.toml: config_version ska vara 1")
    return data


def apply_catalog(products: dict, catalog: dict | None) -> dict:
    """Byter antagen frakt och tryckyta mot Printifys verkliga värden när en ögonblicksbild finns."""
    products = {k: dict(v) for k, v in products.items()}
    for p in products.values():
        p["verified"] = []
    for snap in (catalog or {}).get("snapshots", []):
        for p in products.values():
            if p["search"].split()[0] in str(snap.get("title", "")).lower():
                us = snap.get("shipping_standard", {}).get("US", {})
                if us.get("first_item_minor_max") and us.get("currency") == "USD":
                    p["shipping_us"] = us["first_item_minor_max"]
                    p["verified"].append(f"frakt till USA från Printifys API ({catalog.get('read_on')})")
                costs = [v["cost_minor"] for v in snap.get("variants", []) if v.get("cost_minor")]
                if costs:
                    p["base_cost"] = max(costs)
                    p["verified"].append(f"baspris från Printifys API ({catalog.get('read_on')})")
    return products


def listing_for(idea: dict) -> dict:
    return {"title": idea["title"], "tags": idea["tags"], "description": AI_TEXT, "production_partners": ["Printify"],
            "design_text": idea.get("text", ""), "uses_ai": True}


def economics(idea: dict, product: dict) -> dict:
    normal = unit(idea["price"], product["base_cost"], product["shipping_us"])
    pessimistic = unit(idea["price"], product["base_cost"] * 12 // 10, product["shipping_us"] * 13 // 10,
                       product["shipping_us"], offsite_share_bp=2_500)
    return {"normal": normal.as_dict(), "pessimistic": pessimistic.as_dict()}


def render(idea: dict, product: dict, folder: Path) -> list[str]:
    width, height = product["print_px"]
    preview_h = round(PREVIEW_W * height / width)
    files = []
    for name, (w, h) in (("design.png", (width, height)), ("preview.png", (PREVIEW_W, preview_h))):
        if idea["design"] == "text":
            img = render_text(idea["text"], w, h, idea.get("color", "#1f2d2a"))
        else:
            img = render_pattern(idea["pattern"], w, h, tuple(idea.get("colors", ("#1f3a5f", "#f4f1e8"))))
        write_png(img, folder / name)
        files.append(name)
    return files


def assess(config, config_dir, ideas: list[dict], products: dict, demand: dict, founder: str, runs=None, days=None) -> dict:
    """Spärren D-058 för varje idé, i en tillfällig sim-databas. Returnerar {idé: bedömningens resultat}."""
    from ..memory import Database
    from ..registry import import_file
    from ..simulation.agents import ensure_org
    from ..simulation.assessment import assess_initiative
    from ..system import build_system

    out = {}
    with tempfile.TemporaryDirectory() as tmp, Database.open(Path(tmp) / "data", "sim") as db:
        system = build_system(config, db, config_dir)
        ensure_org(system.registry, founder)
        import_file(system.register, founder, Path(config_dir) / "registry" / "platforms.toml")
        for idea in ideas:
            p = products[idea["product"]]
            item = {"platform": "etsy", "department": "research", "offering": "product",
                    "description": idea["title"],
                    # kunden betalar frakten: den ingår i ordern, och Printifys frakt i styckkostnaden
                    "price_minor": idea["price"] + p["shipping_us"], "unit_cost_minor": p["base_cost"] + p["shipping_us"],
                    "currency": "USD", "founder_hours_per_week": demand["founder_hours_per_week"],
                    "demand": {k: demand[k] for k in ("visitors_per_day", "conversion_bp", "refund_bp", "source")}}
            system.register.record(founder, "initiative", idea["key"], "idea", item, "Q4-idé (D-066)")
            a = assess_initiative(config, config_dir, system.register, idea["key"], founder, runs, days)
            out[idea["key"]] = {"ready": a.ready, "reasons": a.result["reasons"],
                                "scenarios": {k: {"median_adjusted_after_tax_minor": v["median_adjusted_after_tax_minor"],
                                                  "daily_net_minor": v["daily_net_minor"]}
                                              for k, v in a.result["scenarios"].items()},
                                "assumptions": a.result["assumptions"], "runs": a.result["runs"], "days": a.result["days"]}
    return out


def run(config_dir: Path | str, out_dir: Path | str, founder: str, catalog_path: Path | str | None = None,
        runs: int | None = None, days: int | None = None, gate: bool = True) -> dict:
    from ..config import load_config

    config_dir, out_dir = Path(config_dir), Path(out_dir)
    data = load_ideas(out_dir / "ideas.toml")
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8")) if catalog_path else None
    products = apply_catalog(data["products"], catalog)
    rules = load_pod_config(config_dir)["etsy"]["listing_rules"]
    blocklist = load_blocklist(config_dir)
    results, passed = {}, []
    for idea in data["ideas"]:
        problems = listing_problems(listing_for(idea), rules, blocklist)
        entry = {"idea": idea, "problems": problems}
        if not problems:
            folder = out_dir / idea["key"]
            entry["files"] = render(idea, products[idea["product"]], folder)
            entry["economics"] = economics(idea, products[idea["product"]])
            passed.append(idea)
        results[idea["key"]] = entry
    if gate and passed:
        for key, verdict in assess(load_config(config_dir), config_dir, passed, products, data["demand"], founder,
                                   runs, days).items():
            results[key]["gate"] = verdict
    ranked = sorted((r for r in results.values() if "economics" in r),
                    key=lambda r: (r.get("gate", {}).get("ready", False),
                                   r["economics"]["pessimistic"]["profit_after_tax"]), reverse=True)
    for r in results.values():
        if "economics" in r:
            (out_dir / r["idea"]["key"] / "README.md").write_text(idea_readme(r, products, data["demand"]), encoding="utf-8")
    (out_dir / "REPORT.md").write_text(report(ranked, results, products, data["demand"]), encoding="utf-8")
    return {"results": results, "ranked": [r["idea"]["key"] for r in ranked]}


def _usd(cents: int) -> str:
    return f"{cents / 100:.2f} USD"


def idea_readme(r: dict, products: dict, demand: dict) -> str:
    idea, e = r["idea"], r["economics"]
    p = products[idea["product"]]
    n, pe = e["normal"], e["pessimistic"]
    gate = r.get("gate")
    lines = [f"# {idea['title']}", "", "**Status: UTKAST.** Inget är publicerat, och inget utkast finns i Printify.", "",
             f"- **Tema:** {idea['theme']}",
             f"- **Produkt:** {idea['product']}, sökt i Printifys katalog som \"{p['search']}\"",
             f"- **Design:** {'typografi: ' + idea['text'].replace(chr(10), ' / ') if idea['design'] == 'text' else 'mönster: ' + idea['pattern']} "
             f"(egen design, PNG {p['print_px'][0]} × {p['print_px'][1]} px, 300 dpi). Filen är `design.png`, och förhandsvisningen `preview.png`.",
             "", "## Annons (utkast)", f"- **Titel:** {idea['title']}", f"- **Taggar:** {', '.join(idea['tags'])}",
             f"- **Beskrivning, med AI-upplysning:** {AI_TEXT}", "- **Produktionspartner:** Printify", "",
             "## Pris och marginal per order", "| | Normal | Pessimistisk |", "|---|---|---|",
             f"| Pris + frakt som kunden betalar | {_usd(n['price'] + n['shipping_charged'])} | {_usd(pe['price'] + pe['shipping_charged'])} |",
             f"| Printify: baspris + frakt | {_usd(n['base_cost'] + n['shipping_cost'])} | {_usd(pe['base_cost'] + pe['shipping_cost'])} |",
             f"| Etsys avgifter (annons, 6,5 %, 4 % + 3 SEK) | {_usd(n['fees'])} | {_usd(pe['fees'])} |",
             f"| Offsite Ads (15 % på en fjärdedel av ordren) | {_usd(n['offsite'])} | {_usd(pe['offsite'])} |",
             f"| Vinst före skatt | {_usd(n['profit_before_tax'])} | {_usd(pe['profit_before_tax'])} |",
             f"| Skatt på vinsten (spår C, 40 %) | {_usd(n['tax_on_profit'])} | {_usd(pe['tax_on_profit'])} |",
             f"| **Vinst efter skatt** | **{_usd(n['profit_after_tax'])}** ({n['margin_bp'] / 100:.1f} %) | **{_usd(pe['profit_after_tax'])}** ({pe['margin_bp'] / 100:.1f} %) |",
             "", f"- **Kostnadernas källa:** {p['cost_source']}" + (f". Verifierat: {', '.join(p['verified'])}" if p.get("verified") else ""),
             f"- **Systemets skattereserv:** 40 % av bruttointäkten (`basis = \"revenue\"`), {_usd(n['reserve_on_revenue'])} per order. Den hålls undan tills skatten är känd, och den används i spärren nedan.", ""]
    lines += ["## Spärren \"simulera före start\" (D-058)"]
    if gate:
        lines += [f"**{'REDO' if gate['ready'] else 'INTE REDO'}** ({gate['runs']} körningar × {gate['days']} dagar per scenario, skriptade agenter).", ""]
        lines += [f"- {k}: median efter skatt och grundarnas tid {v['median_adjusted_after_tax_minor']} SIM, netto per dag {v['daily_net_minor']} SIM"
                  for k, v in gate["scenarios"].items()]
        lines += [f"- skäl: {x}" for x in gate["reasons"]] + [f"- antagande: {x}" for x in gate["assumptions"]]
    else:
        lines.append("Inte körd.")
    lines += ["", "## Valideringsplan", f"- **Antagen efterfrågan:** {demand['visitors_per_day']} besökare per dag, "
              f"{demand['conversion_bp'] / 100:.1f} % konvertering. Källa: {demand['source']}.",
              "- **Försöket:** 30 dagar på Etsy, 0 kr i fasta kostnader. Det börjar först när D-069 är godkänt och spärren säger redo, eller när grundarna uttryckligen beslutar ett försök.",
              "- **Mät:** visningar, favoriter, order och återbetalningar per dag. Importera dem med `python -m aie results import` (D-062). Efter 7 dagar ersätter de uppmätta värdena antagandena i spärren.",
              "- **Fortsätt:** om spärren blir redo med verkliga utfall.",
              "- **Ändra:** pris, titel eller taggar efter 30 dagar, om det finns minst 1 order per 100 visningar men marginalen är för låg.",
              "- **Sluta:** under 1 order per 300 visningar efter 30 dagar, en reklamation om rättigheter, eller en varning från Etsy. Avpublicera och skriv en lärdom.", ""]
    return "\n".join(lines)


def report(ranked: list[dict], results: dict, products: dict, demand: dict) -> str:
    lines = ["# Q4-idéer för print-on-demand (D-066)", "",
             "**Utkast.** Inget är publicerat. Kostnaderna är antaganden där det står så. Spärren är körd med antagen efterfrågan.", "",
             "| # | Idé | Pris | Vinst efter skatt, normal | Pessimistisk | Spärren |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(ranked, 1):
        e, g = r["economics"], r.get("gate")
        lines.append(f"| {i} | [{r['idea']['title'][:60]}]({r['idea']['key']}/README.md) | {_usd(r['idea']['price'])} | "
                     f"{_usd(e['normal']['profit_after_tax'])} ({e['normal']['margin_bp'] / 100:.1f} %) | "
                     f"{_usd(e['pessimistic']['profit_after_tax'])} | {'redo' if g and g['ready'] else 'inte redo' if g else 'ej körd'} |")
    stopped = [r for r in results.values() if r["problems"]]
    if stopped:
        lines += ["", "## Stoppade av reglerna"] + [f"- {r['idea']['key']}: {'; '.join(r['problems'])}" for r in stopped]
    lines += ["", f"Efterfrågan för alla: {demand['source']}.", "",
              "## Varför spärren säger nej",
              "Marginalen per order efter skatt på vinsten är kolumnen \"normal\" ovan. Spärren (D-058) räknar hårdare:",
              "- **Skatten:** systemets skattereserv är 40 % av **bruttointäkten** (`config/tax.toml`: `basis = \"revenue\"`, spår C). "
              "Med marginaler på 15–20 % före skatt räcker det ensamt för att göra nästan varje körning negativ. Att byta till "
              "`basis = \"profit\"` är ett grundarbeslut (D-052). Det får bara ske när skattebehandlingen är bekräftad (Q-05).",
              "- **Grundarnas tid:** 0,25 timmar per vecka à 100 kr räknas som kostnad.",
              "- **Efterfrågan:** 10 besökare och 1,5 % konvertering per dag är ett antagande. Det pessimistiska scenariot tar en fjärdedel av det.",
              "",
              "Kalkylen per order bygger på antagna kostnader tills Printifys API har lästs (#172, printify-catalog)."]
    return "\n".join(lines) + "\n"
