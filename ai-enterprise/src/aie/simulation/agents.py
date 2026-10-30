"""Simuleringens organisation och de skriptade agenterna (Fas 6b-2, D-043).

`ensure_org()` registrerar en minsta organisation enligt §8 om registret är tomt: CEO, de fyra
kontrollfunktionerna, en departementschef och en arbetsagent i research.

`ScriptedPolicy` är en deterministisk "modell" för `RuleProvider`. Den läser samma läge som en riktig
modell får och svarar med åtgärds-JSON. CI och acceptanstesterna kör med den, så att utfallen går att
upprepa och inga nätverksanrop görs. Med `--agents local` används i stället en lokal modell (Ollama) via
samma `LLMGateway`, och alla svar passerar samma parser och spärrar.

Policyn är enkel och försiktig:
- **Departementschefen** listar initiativ som får sälja och pausar ett initiativ som har gått med
  förlust de senaste sju dagarna. Dag 2 köper den annonser för 2 000. När scenariot säger
  `overspend_attempt` försöker den spendera mer än budgeten, och budgetmotorn ska då säga nej.
- **Arbetsagenten** lämnar ett affärsförslag dag 1 och en intäktsprognos per initiativ var sjunde dag.
- **CFO och CRO** gör var sin bedömning vid `conflicting_assessment`. CFO är för och CRO emot.
- **CEO** avgör efter motstridiga bedömningar och väljer det säkrare alternativet (§20 steg 3: hold).
"""
from __future__ import annotations

import json

from ..agents import AgentState
from ..llm import ChatRequest

ORG = (("ceo-1", "ceo", None), ("cfo-1", "cfo", None), ("cro-1", "cro", None), ("comp-1", "compliance", None),
       ("audit-1", "auditor", None), ("lead-1", "research_lead", "ceo-1"), ("res-1", "researcher", "lead-1"))
STATE_MARKER = "LÄGE (JSON):"


def ensure_org(registry, founder: str) -> list[str]:
    """Registrerar organisationen om registret är tomt. Returnerar de agenter som skapades."""
    if any(True for _ in registry.agents()):
        return []
    for agent_id, role, manager in ORG:
        registry.register(agent_id, role, manager, founder, "simuleringens organisation (D-043)")
        for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
            registry.transition(agent_id, state, founder, "simuleringens organisation (D-043)")
    return [a for a, _, _ in ORG]


def read_state(request: ChatRequest) -> dict:
    text = request.messages[-1].content
    return json.loads(text.split(STATE_MARKER, 1)[1])


class ScriptedPolicy:
    def __call__(self, request: ChatRequest) -> str:
        state = read_state(request)
        handler = getattr(self, f"_{state['role']}", None)
        actions = handler(state) if handler else []
        return json.dumps({"actions": actions}, ensure_ascii=False)

    @staticmethod
    def _research_lead(state: dict) -> list[dict]:
        actions = []
        for i in state["initiatives"]:
            if not i["listed"] and not i["held"] and not i["stopped"] and state["day"] >= i["listed_from"]:
                actions.append({"type": "list_for_sale", "initiative": i["initiative"]})
            elif i["listed"] and i["net_last_7"] < 0 and state["day"] >= i["listed_from"] + 5:
                actions.append({"type": "pause_sale", "initiative": i["initiative"],
                                "reason": f"förlust {i['net_last_7']} de senaste sju dagarna"})
        listed = [i for i in state["initiatives"] if i["listed"] or any(a.get("initiative") == i["initiative"] for a in actions)]
        if state["day"] == 2 and listed:
            actions.append({"type": "spend", "initiative": listed[0]["initiative"], "amount": 2_000,
                            "purpose": "annonser", "risk": "low"})
        budget = state["budget"]
        for event in state["events"]:
            if event["kind"] == "overspend_attempt" and budget["remaining"] is not None:
                actions.append({"type": "spend", "initiative": event["initiative"],
                                "amount": budget["remaining"] + 1,
                                "purpose": event.get("note") or "stor annonskampanj", "risk": "medium"})
        return actions

    @staticmethod
    def _researcher(state: dict) -> list[dict]:
        actions = []
        initiatives = state["initiatives"]
        if state["day"] == 1 and initiatives:
            i = initiatives[0]
            actions.append({
                "type": "proposal", "initiative": i["initiative"],
                "customer_problem": "kunder vill ha färdiga mallar", "solution": "digitala mallar",
                "target_group": "småföretagare", "demand_evidence": "sökningar och konkurrenters försäljning",
                "expected_revenue": i["price"] * 30, "costs": i["price"] * 3, "expected_net": i["price"] * 27,
                "max_loss": 10_000, "time_to_first_revenue": "1 vecka", "test_method": "lista i 14 dagar",
                "continue_or_stop": "avbryt om nettot är negativt efter 14 dagar",
            })
        if state["day"] % 7 == 1:
            for i in initiatives:
                if state["day"] < i["listed_from"]:
                    continue
                expected = i["revenue_last_7"]
                actions.append({"type": "forecast", "initiative": i["initiative"], "metric": "revenue",
                                "expected": expected, "low": expected * 7 // 10, "high": expected * 13 // 10 + 1,
                                "due_in_days": 7})
        return actions

    @staticmethod
    def _assessments(state: dict, position: str, reason: str) -> list[dict]:
        return [{"type": "assessment", "initiative": e["initiative"], "position": position, "reason": reason}
                for e in state["events"] if e["kind"] == "conflicting_assessment"]

    def _cfo(self, state: dict) -> list[dict]:
        return self._assessments(state, "for", "marginalen täcker avgifterna")

    def _cro(self, state: dict) -> list[dict]:
        return self._assessments(state, "against", "kundrisken och återbetalningarna är okända")

    @staticmethod
    def _ceo(state: dict) -> list[dict]:
        out = []
        for key, positions in state.get("assessments", {}).items():
            agree = len(set(positions.values())) == 1
            choice = "list" if agree and "for" in positions.values() else "hold"
            out.append({"type": "decide", "initiative": key, "choice": choice,
                        "reason": "enig bedömning" if agree else "oeniga bedömningar; det säkrare alternativet (§20 steg 3)"})
        return out


MODES = ("scripted", "local", "groq")


def agent_data_class(mode: str):
    """Dataklassen som agenternas förfrågningar märks med. Bara `groq` går till en extern leverantör.

    I läget `groq` innehåller förfrågan bara simulerade data: scenariot, SIM-belopp och agenternas roller.
    Den märks därför `public`, och det är tillåtet bara i miljön `sim` med valutan `SIM`
    (`WorkCycle` kontrollerar det, PR 8, D-060). Inga riktiga uppgifter finns i en simulering.
    """
    from ..llm import DataClass

    return DataClass.PUBLIC if mode == "groq" else DataClass.INTERNAL


def build_gateway(system, mode: str = "scripted", config_dir=None, environ=None, transport=None):
    """`LLMGateway` för agenterna. `scripted`: `RuleProvider` med `ScriptedPolicy` (CI, deterministiskt).

    `local`: bara lokala leverantörer ur `providers.toml` (Ollama). Externa leverantörer används aldrig,
    eftersom läget är `internal`-data (DR-13). Svarar ingen lokal modell blir agentens tur tom och
    noteras i dagen; inget betalas och inget skickas ut (D-008).

    `groq` (PR 8, D-060): bara leverantörerna av typen `groq` ur `providers.toml`. Det är Groqs gratisnivå
    med nyckeln i `GROQ_API_KEY`. Ingen annan leverantör används, inte ens `rule`, så att det aldrig byts
    tyst till något annat. När dagens kvot är slut pausas körningen (`WorkCycle`). Det finns ingen betald
    reserv (D-008, D-009). `environ` och `transport` är till för tester. Där mockas nätverket.
    """
    import os

    from ..llm.gateway import LLMGateway
    from ..llm.providers import RuleProvider, urllib_transport
    from ..llm.router import ProviderRouter, QuotaLedger, Slot, load_providers

    if mode == "scripted":
        slots = (Slot(RuleProvider("sim-scripted", ScriptedPolicy()), 1_000_000, 1_000_000_000),)
    elif mode == "local":
        loaded, _ = load_providers(config_dir)
        slots = tuple(s for s in loaded if not s.provider.external and not isinstance(s.provider, RuleProvider))
        if not slots:
            raise ValueError("providers.toml har ingen lokal leverantör (ollama) för --agents local")
    elif mode == "groq":
        loaded, skipped = load_providers(config_dir, environ if environ is not None else os.environ,
                                         transport or urllib_transport)
        slots = tuple(s for s in loaded if getattr(s.provider, "kind", None) == "groq")
        if not slots:
            why = "; ".join(s for s in skipped if s.startswith("groq")) or "providers.toml har ingen groq-leverantör"
            raise ValueError(f"--agents groq kan inte köras: {why}. Se docs/setup.md.")
    else:
        raise ValueError(f"okänt agentläge {mode!r} ({', '.join(MODES)})")
    router = ProviderRouter(slots, QuotaLedger(system.db), system.audit)
    return LLMGateway(router, system.engine, system.audit)
