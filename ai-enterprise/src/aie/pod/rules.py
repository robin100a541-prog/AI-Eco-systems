"""Regler för annonser och motiv (arbetsorder 04, D-067). Reglerna är data i `config/pod.toml` och
`config/ip_blocklist.toml`; koden kontrollerar dem och stoppar det som bryter mot dem.

**Annonsen** (`[etsy.listing_rules]`):
- **Produktionspartner:** tryckpartnern ska anges som produktionspartner, eftersom Etsy kräver det för print-on-demand.
- **AI:** AI-användning ska stå i beskrivningen (Etsys regler för "Seller-prompted AI creations").
- **Gränser för titel och taggar:** titeln har en högsta längd, och taggarna har både ett högsta antal och en högsta längd var.

**Motivet** (`design_problems`) prövas mot `ip_blocklist.toml`:
- **Varumärken, figurer och kända personer:** ord och fraser som pekar på någon annans rättigheter.
- **Kopiering:** formuleringar som avslöjar kopiering, till exempel "in the style of" och "fan art".
- **Skyddsmärken:** tecknen ™ och ®.

En träff stoppar. Kontrollen är en spärr mot uppenbara fel och ingen juridisk granskning. Därför står
"egen design" kvar som krav i varje utkast, och Compliance granskar före publicering.
"""
from __future__ import annotations

import re
import tomllib
import unicodedata
from pathlib import Path


def load_blocklist(config_dir: Path | str) -> dict:
    data = tomllib.loads((Path(config_dir) / "ip_blocklist.toml").read_text(encoding="utf-8"))
    if data.get("config_version") != 1:
        raise ValueError("ip_blocklist.toml: config_version ska vara 1")
    return data


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def design_problems(text: str, blocklist: dict) -> list[str]:
    """Varför ett motiv, en titel eller taggar inte får användas. Tom lista betyder att inget hittades."""
    folded = _fold(text)
    problems = []
    for group, terms in (("varumärke eller figur", blocklist.get("trademarks", [])),
                         ("känd person", blocklist.get("people", [])),
                         ("tecken på kopiering", blocklist.get("copy_phrases", []))):
        for term in terms:
            if re.search(rf"(?<![a-z0-9]){re.escape(_fold(term))}(?![a-z0-9])", folded):
                problems.append(f"{group}: {term!r}")
    for mark in blocklist.get("marks", []):
        if mark in text:
            problems.append(f"skyddsmärke {mark!r}")
    return problems


def listing_problems(listing: dict, rules: dict, blocklist: dict) -> list[str]:
    """Kontrollerar en annons mot Etsys regler i `pod.toml` och motivet mot spärrlistan."""
    problems = []
    title, tags = listing.get("title", ""), listing.get("tags", [])
    description = listing.get("description", "")
    if len(title) > rules["max_title_chars"]:
        problems.append(f"titeln är {len(title)} tecken; högst {rules['max_title_chars']}")
    if len(tags) > rules["max_tags"]:
        problems.append(f"{len(tags)} taggar; högst {rules['max_tags']}")
    long_tags = [t for t in tags if len(t) > rules["max_tag_chars"]]
    if long_tags:
        problems.append(f"taggar över {rules['max_tag_chars']} tecken: {', '.join(long_tags)}")
    partner = rules.get("production_partner")
    if partner and partner not in listing.get("production_partners", []):
        problems.append(f"{partner} är inte angiven som produktionspartner (Etsy kräver det)")
    if rules.get("require_ai_disclosure") and listing.get("uses_ai", True):
        if not any(_fold(p) in _fold(description) for p in rules.get("ai_disclosure_phrases", [])):
            problems.append("AI-användningen står inte i beskrivningen (Etsy kräver det)")
    problems += design_problems(" ".join([title, description, *tags, listing.get("design_text", "")]), blocklist)
    return problems
