"""Åtgärdsprotokollet: vad en agent får föreslå i simuleringen (Fas 6b-2, D-043, FR-23, §12, §20).

En agent svarar med JSON: `{"actions": [ ... ]}`. Svaret är alltid en obekräftad hypotes (§29).
Ingenting i svaret ger behörighet. Varje åtgärd valideras här och passerar sedan `AuthorizationEngine`
och, för pengar, `BudgetEngine` i arbetscykeln.

| Typ | Fält | Verktyg | Vad som händer |
|---|---|---|---|
| `forecast` | initiative, metric (net/revenue/costs), expected, low?, high?, due_in_days | `forecast.make` | prognos i `ForecastLog` (FR-16) |
| `spend` | initiative, amount, purpose, risk (low/medium/high) | `sim.spend` | budgetkontroll; vid ja bokförs en kostnad |
| `list_for_sale` | initiative | `sales.list` | initiativet säljer från i dag (momsgränsen gäller, ER-20) |
| `pause_sale` | initiative, reason | `sales.list` | initiativet slutar sälja |
| `proposal` | initiative + de 11 fälten i §12 | `proposal.submit` | ett affärsförslag; saknas ett fält avvisas det |
| `assessment` | initiative, position (for/against), reason | `report.write` | en bedömning; motstridiga bedömningar dokumenteras (§21) |
| `decide` | initiative, choice (list/hold), reason | `decision.record` | CEO avgör efter motstridiga bedömningar |
| `report` | title, text | `report.write` | en rapport, en hypotes |

Ett svar som inte är giltig JSON, en okänd typ, ett fält som saknas eller fler än `MAX_ACTIONS` åtgärder
avvisas. Avvisningen syns i dagens sammanfattning och i revisionsloggen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

MAX_ACTIONS = 10
TOOLS = {
    "forecast": "forecast.make",
    "spend": "sim.spend",
    "list_for_sale": "sales.list",
    "pause_sale": "sales.list",
    "proposal": "proposal.submit",
    "assessment": "report.write",
    "decide": "decision.record",
    "report": "report.write",
}
PROPOSAL_FIELDS = {  # §12: varje affärsförslag ska innehålla
    "customer_problem": "Kundproblem",
    "solution": "Föreslagen lösning",
    "target_group": "Identifierad målgrupp",
    "demand_evidence": "Belägg för efterfrågan",
    "expected_revenue": "Förväntade intäkter",
    "costs": "Samtliga relevanta kostnader",
    "expected_net": "Förväntad nettovinst",
    "max_loss": "Möjlig maximal förlust",
    "time_to_first_revenue": "Tid till första intäkt",
    "test_method": "Testmetod",
    "continue_or_stop": "Kriterier för att fortsätta eller avbryta",
}
_MONEY = frozenset({"expected_revenue", "costs", "expected_net", "max_loss"})
_REQUIRED = {
    "forecast": ("initiative", "metric", "expected", "due_in_days"),
    "spend": ("initiative", "amount", "purpose", "risk"),
    "list_for_sale": ("initiative",),
    "pause_sale": ("initiative", "reason"),
    "proposal": ("initiative", *PROPOSAL_FIELDS),
    "assessment": ("initiative", "position", "reason"),
    "decide": ("initiative", "choice", "reason"),
    "report": ("title", "text"),
}


@dataclass(frozen=True, slots=True)
class Action:
    type: str
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def tool(self) -> str:
        return TOOLS[self.type]

    def get(self, key: str, default=None):
        return self.fields.get(key, default)


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _extract_json(text: str):
    """Det första JSON-objektet i svaret. En modell kan skriva text runt omkring."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def parse_actions(text: str, initiatives: frozenset[str]) -> tuple[tuple[Action, ...], tuple[str, ...]]:
    """Returnerar (giltiga åtgärder, avvisningar med skäl). Ogiltiga åtgärder utförs aldrig."""
    data = _extract_json(text or "")
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        return (), ('svaret är inte JSON med "actions": [...] (D-043)',)
    raw = data["actions"]
    errors: list[str] = []
    if len(raw) > MAX_ACTIONS:
        errors.append(f"{len(raw)} åtgärder; högst {MAX_ACTIONS} per agent och dag tas emot")
        raw = raw[:MAX_ACTIONS]
    actions: list[Action] = []
    for n, item in enumerate(raw, 1):
        problem = validate_action(item, initiatives)
        if problem:
            errors.append(f"åtgärd {n}: {problem}")
        else:
            actions.append(Action(item["type"], {k: v for k, v in item.items() if k != "type"}))
    return tuple(actions), tuple(errors)


def validate_action(item, initiatives: frozenset[str]) -> str | None:
    if not isinstance(item, dict):
        return "ska vara ett objekt"
    kind = item.get("type")
    if kind not in TOOLS:
        return f"okänd typ {kind!r} (tillåtna: {', '.join(TOOLS)})"
    missing = [k for k in _REQUIRED[kind] if k not in item]
    if missing:
        return f"{kind} saknar {', '.join(missing)}"
    if "initiative" in _REQUIRED[kind] and item["initiative"] not in initiatives:
        return f"okänt initiativ {item['initiative']!r}"
    if kind == "forecast":
        if item["metric"] not in ("net", "revenue", "costs"):
            return "metric ska vara net, revenue eller costs"
        if not all(_int(item.get(k, 0)) for k in ("expected", "low", "high")):
            return "expected, low och high ska vara heltal i minsta enhet (D-006)"
        if not _int(item["due_in_days"]) or not 1 <= item["due_in_days"] <= 365:
            return "due_in_days ska vara 1–365"
    elif kind == "spend":
        if not _int(item["amount"]) or item["amount"] <= 0:
            return "amount ska vara ett heltal > 0 i minsta enhet (D-006)"
        if item["risk"] not in ("low", "medium", "high"):
            return "risk ska vara low, medium eller high (critical tillåts aldrig, §24)"
        if not _text(item["purpose"]):
            return "purpose saknas"
    elif kind == "proposal":
        empty = [PROPOSAL_FIELDS[k] for k in PROPOSAL_FIELDS
                 if not (_int(item[k]) if k in _MONEY else _text(item[k]))]
        if empty:
            return f"affärsförslaget saknar eller har fel i: {', '.join(empty)} (§12, FR-23)"
    elif kind == "assessment":
        if item["position"] not in ("for", "against") or not _text(item["reason"]):
            return "position ska vara for eller against, med reason"
    elif kind == "decide":
        if item["choice"] not in ("list", "hold") or not _text(item["reason"]):
            return "choice ska vara list eller hold, med reason"
    elif kind in ("pause_sale",):
        if not _text(item["reason"]):
            return "reason saknas"
    elif kind == "report":
        if not (_text(item["title"]) and _text(item["text"])):
            return "title och text krävs"
    return None


def schema_text() -> str:
    """Instruktionen till modellen: vilka åtgärder som finns och hur svaret ska se ut."""
    lines = ['Svara ENBART med JSON: {"actions": [ ... ]}. Tom lista om du inte vill göra något.',
             f"Högst {MAX_ACTIONS} åtgärder. Belopp är heltal i öre (SIM). Typer och fält:"]
    for kind, keys in _REQUIRED.items():
        lines.append(f"- {kind}: {', '.join(keys)}")
    lines.append("Allt du föreslår är en hypotes. Systemets spärrar avgör vad som faktiskt sker.")
    return "\n".join(lines)
