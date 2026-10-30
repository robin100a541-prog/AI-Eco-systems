"""Produktagenten (Fas 7a): föreslår tre digitala produkter och skriver den valda produkten.

Modellen svarar med JSON. Koden räknar själv alla pengar (Gumroads avgift 10 % + 0,50 USD, netto per
försäljning, förväntat netto och största förlust), så att modellens siffror aldrig används oprövade.
Ett svar som saknar fält eller har siffror som inte stämmer avvisas, och då används regelförslagen
(`RULE_IDEAS`). Efterfrågan är alltid `unverified` tills riktig försäljning finns (D-062, D-063):
en modell kan inte verifiera efterfrågan.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from ..llm import ChatRequest, DataClass, Message

GUMROAD_PERCENT = 10
GUMROAD_FIXED_CENTS = 50
AGENT = "res-1"  # researcher: har llm.complete och proposal.submit
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,40}$")
REQUIRED = ("id", "title", "format", "target_customer", "problem", "demand_evidence", "price_usd",
            "upfront_costs_usd", "expected_sales_90d", "time_to_first_sale_days", "continue_criteria",
            "stop_criteria")


class IdeaError(ValueError):
    """Förslaget är ofullständigt eller har siffror som inte stämmer."""


@dataclass(frozen=True, slots=True)
class Idea:
    id: str
    title: str
    format: str  # "pdf-guide" eller "template"
    target_customer: str
    problem: str
    demand_evidence: tuple[str, ...]
    demand_status: str  # alltid "unverified" tills riktig försäljning finns
    price_cents: int
    upfront_costs_cents: int  # allt som betalas innan första försäljningen (0 = inga)
    expected_sales_90d: int
    time_to_first_sale_days: int
    continue_criteria: str
    stop_criteria: str

    @property
    def fee_cents(self) -> int:
        return (self.price_cents * GUMROAD_PERCENT + 50) // 100 + GUMROAD_FIXED_CENTS

    @property
    def net_per_sale_cents(self) -> int:
        return self.price_cents - self.fee_cents

    @property
    def expected_net_90d_cents(self) -> int:
        return self.expected_sales_90d * self.net_per_sale_cents - self.upfront_costs_cents

    @property
    def max_loss_cents(self) -> int:
        """Största förlust: förskottskostnaderna. Gumroad tar bara avgift när något säljs."""
        return self.upfront_costs_cents

    def as_dict(self) -> dict:
        d = asdict(self)
        d["demand_evidence"] = list(self.demand_evidence)
        d.update(fee_cents=self.fee_cents, net_per_sale_cents=self.net_per_sale_cents,
                 expected_net_90d_cents=self.expected_net_90d_cents, max_loss_cents=self.max_loss_cents)
        return d


def _cents(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise IdeaError(f"{name} måste vara ett tal >= 0")
    return round(value * 100)


def parse_idea(raw: dict) -> Idea:
    """Validerar ett förslag i kod. Kastar `IdeaError` med alla fel."""
    if not isinstance(raw, dict):
        raise IdeaError("förslaget är inget JSON-objekt")
    missing = [k for k in REQUIRED if raw.get(k) in (None, "", [])]
    if missing:
        raise IdeaError("saknar " + ", ".join(missing))
    errors = []
    if not isinstance(raw["id"], str) or not _SLUG.fullmatch(raw["id"]):
        errors.append("id måste vara a-z, 0-9 och bindestreck")
    if raw["format"] not in ("pdf-guide", "template"):
        errors.append("format måste vara pdf-guide eller template")
    evidence = raw["demand_evidence"]
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, list) or not all(isinstance(e, str) and e.strip() for e in evidence):
        errors.append("demand_evidence måste vara en lista med text")
    for key in ("title", "target_customer", "problem", "continue_criteria", "stop_criteria"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            errors.append(f"{key} måste vara text")
    try:
        price = _cents(raw["price_usd"], "price_usd")
        upfront = _cents(raw["upfront_costs_usd"], "upfront_costs_usd")
    except IdeaError as exc:
        errors.append(str(exc))
        price = upfront = 0
    if not 100 <= price <= 10_000:
        errors.append("priset måste vara 1–100 USD")
    for key in ("expected_sales_90d", "time_to_first_sale_days"):
        if isinstance(raw[key], bool) or not isinstance(raw[key], int) or raw[key] < 0:
            errors.append(f"{key} måste vara ett heltal >= 0")
    if errors:
        raise IdeaError("; ".join(errors))
    idea = Idea(raw["id"], raw["title"].strip(), raw["format"], raw["target_customer"].strip(),
                raw["problem"].strip(), tuple(e.strip() for e in evidence), "unverified", price, upfront,
                raw["expected_sales_90d"], raw["time_to_first_sale_days"], raw["continue_criteria"].strip(),
                raw["stop_criteria"].strip())
    claimed = raw.get("expected_net_90d_usd")
    if claimed is not None and abs(_cents(abs(claimed), "expected_net_90d_usd") * (1 if claimed >= 0 else -1)
                                   - idea.expected_net_90d_cents) > 100:
        raise IdeaError(f"expected_net_90d_usd {claimed} stämmer inte med kodens beräkning "
                        f"{idea.expected_net_90d_cents / 100:.2f}")
    return idea


RULE_IDEAS = (
    {"id": "frilans-fakturamall", "title": "Fakturamall för svenska frilansare (F-skatt)", "format": "template",
     "target_customer": "Nya frilansare och enskilda firmor i Sverige",
     "problem": "Vet inte vad en korrekt svensk faktura måste innehålla (moms, F-skatt, OCR, förfallodag)",
     "demand_evidence": ["antagande: många nya enskilda firmor varje år; ingen egen mätning"],
     "price_usd": 9, "upfront_costs_usd": 0, "expected_sales_90d": 10, "time_to_first_sale_days": 30,
     "continue_criteria": "minst 3 försäljningar inom 60 dagar och återbetalningar under 10 %",
     "stop_criteria": "ingen försäljning på 60 dagar, eller en återbetalning per tre försäljningar"},
    {"id": "hushallsbudget-mall", "title": "Hushållsbudget i kalkylark med sparmål", "format": "template",
     "target_customer": "Hushåll i Sverige som vill få koll på sina utgifter",
     "problem": "Saknar en enkel budget på svenska med månadsflikar och sparmål",
     "demand_evidence": ["antagande: budgetmallar säljs på flera plattformar; ingen egen mätning"],
     "price_usd": 5, "upfront_costs_usd": 0, "expected_sales_90d": 12, "time_to_first_sale_days": 30,
     "continue_criteria": "minst 4 försäljningar inom 60 dagar", "stop_criteria": "ingen försäljning på 60 dagar"},
    {"id": "f-skatt-guide", "title": "Guide: starta enskild firma med F-skatt steg för steg", "format": "pdf-guide",
     "target_customer": "Personer som vill börja fakturera vid sidan av jobbet",
     "problem": "Osäkra på registrering, F-skatt, moms och bokföring första året",
     "demand_evidence": ["antagande: vanlig fråga i forum; ingen egen mätning"],
     "price_usd": 12, "upfront_costs_usd": 0, "expected_sales_90d": 8, "time_to_first_sale_days": 30,
     "continue_criteria": "minst 3 försäljningar inom 60 dagar",
     "stop_criteria": "ingen försäljning på 60 dagar, eller återbetalningar över 15 %"},
)

SYSTEM_PROMPT = (
    "Du är produktagenten i ett litet AI-företag. Föreslå exakt 3 digitala produkter (en PDF-guide eller en mall) "
    "som en grundare kan lista för hand på Gumroad. Inga betalda verktyg, ingen annonsering, inga kunduppgifter. "
    "Gumroad tar 10 % + 0,50 USD per försäljning. Svara ENDAST med JSON: {\"ideas\": [ {\"id\": \"slug\", "
    "\"title\": str, \"format\": \"pdf-guide\"|\"template\", \"target_customer\": str, \"problem\": str, "
    "\"demand_evidence\": [str], \"price_usd\": number, \"upfront_costs_usd\": number, \"expected_sales_90d\": int, "
    "\"time_to_first_sale_days\": int, \"expected_net_90d_usd\": number, \"continue_criteria\": str, "
    "\"stop_criteria\": str} ]}. expected_net_90d_usd = expected_sales_90d * (price - 10 % - 0,50) - upfront_costs. "
    "Skriv på svenska. Efterfrågan är ett antagande; påstå inte att den är verifierad."
)


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise IdeaError("svaret innehåller ingen JSON")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise IdeaError(f"ogiltig JSON: {exc.msg}") from exc


def propose(gateway, data_class: DataClass = DataClass.PUBLIC) -> tuple[tuple[Idea, ...], dict]:
    """Tre förslag från modellen, eller regelförslagen om svaret inte håller. Returnerar (idéer, logg)."""
    log = {"source": "model", "rejected": [], "provider": None}
    try:
        response = gateway.complete(AGENT, ChatRequest(
            (Message("system", SYSTEM_PROMPT), Message("user", "Föreslå tre produkter nu.")), data_class, 2_000))
        log["provider"] = f"{response.provider}/{response.model}"
        raw = _extract_json(response.text).get("ideas")
        if not isinstance(raw, list):
            raise IdeaError("ideas saknas")
        ideas = []
        for item in raw:
            try:
                ideas.append(parse_idea(item))
            except IdeaError as exc:
                log["rejected"].append(str(exc))
        if len(ideas) < 3:
            raise IdeaError(f"bara {len(ideas)} giltiga förslag av 3")
        return tuple(ideas[:3]), log
    except Exception as exc:  # noqa: BLE001 — varje fel ger regelförslagen, och felet loggas
        log.update(source="rule", reason=f"{type(exc).__name__}: {exc}")
        return tuple(parse_idea(r) for r in RULE_IDEAS), log
