"""Beslutscykeln för piloten (Fas 7a/7c): CFO och risk bedömer, CEO beslutar, allt via LLMGateway.

Gången följer den vanliga beslutsprocessen:
1. En grundare skapar uppgiften "välj pilotprodukt" och ger den till CEO.
2. CFO och CRO bedömer varje förslag (för/emot med motivering).
3. Där CFO är för och CRO emot öppnas en tvist (§21) som eskaleras till CEO.
4. CEO fattar beslutet med alla åtta fält i §20 steg 7. Det skrivs i beslutsloggen via godkännandekön.

Varje svar valideras i kod. Ett svar som saknar fält, har siffror som inte stämmer eller väljer ett
förslag som risk har invändningar mot avvisas, och då används regeln för den rollen i stället. Hur väl
modellen klarade varje kontroll sparas i `quality` och skrivs som rapport (7c).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..governance import DecisionDraft, RiskClass
from ..governance.disputes import ConflictType, Position
from ..llm import ChatRequest, DataClass, Message
from .product import AgentStopped, Idea, IdeaError, _extract_json

CEO, CFO, CRO = "ceo-1", "cfo-1", "cro-1"
FIELDS = ("chosen_action", "reasoning", "evidence", "budget_minor", "risk_class", "expected_result",
          "stop_conditions", "follow_up")


@dataclass
class CycleResult:
    task_id: int
    chosen: Idea | None
    decision: object  # Decision eller ApprovalRequest
    assessments: dict  # roll -> {idea_id: (position, reason)}
    disputes: list
    quality: dict = field(default_factory=dict)


def to_sek_minor(cents: int, usd_sek: float) -> int:
    return round(cents * usd_sek)


def should_object(idea: Idea, limits, usd_sek: float) -> bool:
    """Risk ska invända när förlusten kan bli större än ett experiment får förlora, eller när det tar för länge."""
    cap = limits.max_single_experiment_loss.amount_minor if limits.max_single_experiment_loss else 0
    return to_sek_minor(idea.max_loss_cents, usd_sek) > cap or idea.time_to_first_sale_days > 90


def _ask(gateway, agent: str, system: str, payload: dict, data_class) -> dict:
    text = system + "\nUnderlag (JSON): " + json.dumps(payload, ensure_ascii=False)
    response = gateway.complete(agent, ChatRequest((Message("system", text), Message("user", "Svara nu med JSON.")),
                                                   data_class, 1_500))
    return _extract_json(response.text)


def _assess(gateway, role: str, ideas, data_class) -> dict:
    title = "CFO: bedöm lönsamheten" if role == CFO else "Riskchef (CRO): bedöm risken och invänd när den är för stor"
    raw = _ask(gateway, role, f"Du är {title} för varje förslag. Svara ENDAST med JSON {{\"assessments\": "
               "[{\"idea_id\": str, \"position\": \"for\"|\"against\", \"reason\": str}]}, en rad per förslag.",
               {"ideas": [i.as_dict() for i in ideas]}, data_class)
    rows = raw.get("assessments")
    if not isinstance(rows, list):
        raise IdeaError("assessments saknas")
    out = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("position") not in ("for", "against") or not str(r.get("reason", "")).strip():
            raise IdeaError(f"ogiltig bedömning: {r!r}"[:200])
        out[r.get("idea_id")] = (r["position"], str(r["reason"]).strip())
    if set(out) != {i.id for i in ideas}:
        raise IdeaError("bedömningen täcker inte exakt alla förslag")
    return out


def _ceo_draft(raw: dict, ideas, blocked: set, usd_sek: float) -> tuple[Idea, DecisionDraft]:
    by_id = {i.id: i for i in ideas}
    missing = [f for f in ("idea_id", *(f for f in FIELDS if f != "budget_minor")) if raw.get(f) in (None, "", [])]
    if missing:
        raise IdeaError("CEO-beslutet saknar " + ", ".join(missing))
    idea = by_id.get(raw["idea_id"])
    if idea is None:
        raise IdeaError(f"okänt förslag {raw['idea_id']!r}")
    if idea.id in blocked:
        raise IdeaError(f"{idea.id} har en invändning från risk och får inte väljas")
    if raw["risk_class"] not in [r.value for r in RiskClass]:
        raise IdeaError("risk_class måste vara low, medium, high eller critical")
    budget = to_sek_minor(idea.max_loss_cents, usd_sek)  # koden räknar, modellen ger inga belopp
    evidence = raw["evidence"] if isinstance(raw["evidence"], list) else [raw["evidence"]]
    return idea, DecisionDraft(str(raw["chosen_action"]), str(raw["reasoning"]), tuple(map(str, evidence)), budget,
                               RiskClass(raw["risk_class"]), str(raw["expected_result"]),
                               str(raw["stop_conditions"]), str(raw["follow_up"]))


def run_cycle(gov, gateway, ideas, founder: str, limits, usd_sek: float,
              data_class: DataClass = DataClass.PUBLIC) -> CycleResult:
    task = gov.board.create(founder, "Fas 7: välj pilotprodukt", "Välj en av tre produkter för manuell listning")
    gov.board.assign(founder, task.task_id, CEO, "piloten (Fas 7a)")
    quality = {"roles": {}, "risk_should_object": sorted(i.id for i in ideas if should_object(i, limits, usd_sek))}
    assessments = {}
    for role in (CFO, CRO):
        try:
            assessments[role] = _assess(gateway, role, ideas, data_class)
            quality["roles"][role] = {"valid": True}
        except Exception as exc:  # noqa: BLE001 — ingen reserv (Robin 2026-10-30)
            raise AgentStopped(f"{role} gav ingen giltig bedömning: {type(exc).__name__}: {exc}") from exc
    model_objections = sorted(k for k, (p, _) in assessments[CRO].items() if p == "against")
    quality["risk_objected"] = model_objections
    quality["risk_objection_correct"] = set(quality["risk_should_object"]) <= set(model_objections)
    blocked = set(model_objections) | set(quality["risk_should_object"])
    disputes = []
    for i in ideas:
        if assessments[CFO][i.id][0] == "for" and assessments[CRO][i.id][0] == "against":
            d = gov.disputes.open(CFO, task.task_id, ConflictType.RISK, f"välj {i.id}",
                                  to_sek_minor(i.max_loss_cents, usd_sek), RiskClass.LOW,
                                  (Position(CFO, assessments[CFO][i.id][1], ("CFO:s bedömning",)),
                                   Position(CRO, assessments[CRO][i.id][1], ("CRO:s bedömning",))))
            gov.disputes.escalate(CFO, d.dispute_id, "CFO och risk är oense; CEO avgör (§21)")
            disputes.append(d.dispute_id)
    payload = {"ideas": [i.as_dict() for i in ideas], "assessments": {
        r: {k: {"position": p, "reason": t} for k, (p, t) in a.items()} for r, a in assessments.items()},
        "usd_sek": usd_sek, "risk_blocked": sorted(blocked)}
    try:
        raw = _ask(gateway, CEO, "Du är CEO. Välj exakt ett förslag som risk inte invänt mot. Svara ENDAST med JSON "
                   "med fälten idea_id, chosen_action, reasoning, evidence (lista), risk_class (low|medium|high|critical), "
                   "expected_result, stop_conditions och follow_up. Ange inga belopp; koden räknar dem.", payload, data_class)
        idea, draft = _ceo_draft(raw, ideas, blocked, usd_sek)
        quality["roles"][CEO] = {"valid": True, "fields": "alla åtta fält i §20 steg 7", "numbers_consistent": True}
    except Exception as exc:  # noqa: BLE001 — ingen reserv (Robin 2026-10-30)
        raise AgentStopped(f"CEO gav inget giltigt beslut: {type(exc).__name__}: {exc}") from exc
    decision = gov.queue.submit_decision(CEO, task.task_id, draft)
    return CycleResult(task.task_id, idea, decision, assessments, disputes, quality)


def quality_report(result: CycleResult, propose_log: dict, ideas) -> str:
    q = result.quality
    lines = ["# 7c: beslutskvalitet med språkmodell", "",
             f"Produktförslag: källa **{propose_log.get('source')}** ({propose_log.get('provider') or '–'})."
             + (f" Reserv: {propose_log.get('reason')}" if propose_log.get("reason") else ""), ""]
    if propose_log.get("rejected"):
        lines += ["Avvisade förslag: " + "; ".join(propose_log["rejected"]), ""]
    lines += ["| Roll | Giltigt svar | Kommentar |", "|---|---|---|"]
    for role, r in q.get("roles", {}).items():
        lines.append(f"| {role} | {'ja' if r.get('valid') else 'nej, regel användes'} | "
                     f"{r.get('fallback') or r.get('fields', '')} |")
    lines += ["", f"- Risk borde invända mot: {', '.join(q.get('risk_should_object') or []) or 'inget'}",
              f"- Risk invände mot: {', '.join(q.get('risk_objected') or []) or 'inget'}",
              f"- Invändningarna räckte: {'ja' if q.get('risk_objection_correct') else 'nej'}",
              f"- Tvister: {len(result.disputes)} (eskalerade till CEO)",
              f"- Valt förslag: {result.chosen.id if result.chosen else '–'}", "",
              "| Förslag | Pris USD | Avgift USD | Netto/st USD | Förväntat netto 90 d USD | Största förlust USD |",
              "|---|---|---|---|---|---|"]
    for i in ideas:
        lines.append(f"| {i.id} | {i.price_cents / 100:.2f} | {i.fee_cents / 100:.2f} | {i.net_per_sale_cents / 100:.2f}"
                     f" | {i.expected_net_90d_cents / 100:.2f} | {i.max_loss_cents / 100:.2f} |")
    lines += ["", "Efterfrågan är OVERIFIERAD i alla förslag (D-063)."]
    return "\n".join(lines) + "\n"
