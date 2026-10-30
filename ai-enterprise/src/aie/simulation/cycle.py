"""Arbetscykeln: agenterna arbetar en simulerad dag i taget (Fas 6b-2, FR-20, §20, D-043).

Ett varv är en dag och följer §20:
1. **Dagen börjar** (`Simulation.begin_day`): scenariots aktörshändelser, till exempel intrång eller nödstopp.
2. **Läget** byggs från ledgern, budgeten, spärrarna och de föregående dagarna. Det skickas till
   agenterna via `LLMGateway` som `internal`-data, så bara lokala leverantörer kan ta emot det (DR-13).
3. **Agenterna svarar** med åtgärder (`actions.parse_actions`). Arbetsagenten svarar först
   (förslag och prognoser), sedan departementschefen (listning och utgifter). Vid motstridiga
   bedömningar svarar CFO och CRO, och sedan avgör CEO.
4. **Varje åtgärd** kontrolleras av `AuthorizationEngine` (rätt verktyg, nödstopp, skyddat läge,
   momsgräns). Utgifter kontrolleras också av `BudgetEngine` (budget, reserv, skattereserv,
   stop-loss, uppdelade köp). Bara det som får ja genomförs.
5. **Marknaden och bokföringen** (`Simulation.finish_day`) säljer det som är listat och inte stoppat,
   kör `System.tick()` och sparar dagen med agenternas åtgärder och resultat.

Inget här kan röra riktiga pengar. Simuleringen körs bara i `sim` (D-042), utgifter bokförs i `SIM`
av `system:simulation`, och inga betalnings- eller nätverksverktyg finns.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from ..agents import ACTING_STATES
from ..authorization import PermissionDenied
from ..budget import BudgetBlocked, Risk, SpendRequest
from ..evaluation import ForecastError
from ..ledger import Approval, EntryDraft, EntryType, Status, compute_result
from ..llm import ChatRequest, DataClass, Message, NoProviderAvailable
from ..llm.gateway import SecretInPrompt
from .actions import TOOLS, Action, parse_actions, schema_text
from .agents import STATE_MARKER
from .run import SYSTEM, Simulation

ORDER = ("researcher", "research_lead")  # varje dag; CFO, CRO och CEO bara vid motstridiga bedömningar
ROLE_ACTIONS = {
    "researcher": ("proposal", "forecast", "report"),
    "research_lead": ("list_for_sale", "pause_sale", "spend", "forecast", "proposal", "report"),
    "cfo": ("assessment", "forecast", "report"),
    "cro": ("assessment", "report"),
    "ceo": ("decide", "forecast", "report"),
}


class WorkCycle:
    def __init__(self, sim: Simulation, system, gateway, data_class: DataClass = DataClass.INTERNAL) -> None:
        """`data_class`: `public` bara för `--agents groq`, och bara i miljön sim med SIM (PR 8, D-060)."""
        if data_class is not DataClass.INTERNAL:
            from .run import require_sim

            require_sim(sim.config)  # en simulering innehåller inga riktiga uppgifter; prod skickas aldrig ut
        self.sim = sim
        self._system = system
        self._gateway = gateway
        self._data_class = data_class
        self._initiatives = frozenset(i.key for i in sim.scenario.initiatives)
        self.paused: str | None = None  # varför körningen pausades, till exempel att kvoten tog slut

    def run(self, days: int | None = None) -> list[dict]:
        """Kör dagar tills målet nås. Räcker inte dagens kvot hos leverantörerna till en hel dag pausas
        körningen före dagen. Inget halvt dygn sparas, och `simulate resume` fortsätter (PR 8)."""
        target = self.sim.scenario.days if days is None else min(self.sim.scenario.days, self.sim.last_day + days)
        out = []
        self.paused = None
        while self.sim.last_day < target:
            needed = self._calls_needed(self.sim.last_day + 1)
            left = self._gateway.calls_left() if hasattr(self._gateway, "calls_left") else needed
            if left < needed:
                self.paused = (f"kvoten hos språkmodellen räcker inte till dag {self.sim.last_day + 1} "
                               f"({left} anrop kvar, {needed} behövs); fortsätt med simulate resume när den har "
                               "fyllts på (UTC-dygn). Ingen betald reserv används (D-008, D-009)")
                self._system.audit.append(SYSTEM, "simulation.paused_quota",
                                          {"day": self.sim.last_day + 1, "calls_left": left, "calls_needed": needed})
                break
            out.append(self.day())
        return out

    def _calls_needed(self, day: int) -> int:
        conflict = any(e.day == day and e.kind == "conflicting_assessment" for e in self.sim.scenario.events)
        return len(ORDER) + (3 if conflict else 0)

    def day(self) -> dict:
        previous = self.sim.days()[-1] if self.sim.last_day else {}
        listed = set(previous.get("listed") or ())
        held = set(previous.get("held") or ())
        ctx = self.sim.begin_day()
        record = {"actions": [], "rejected": [], "assessments": {}, "proposals": [], "reports": [],
                  "approved_spends": []}
        events = [e for e in ctx["events"]]
        self._approved_spends(ctx["day"], record)

        for role in ORDER:
            self._turn(role, ctx["day"], events, listed, held, record)
        conflicts = [e for e in events if e.kind == "conflicting_assessment"]
        if conflicts:
            for key in {e.initiative for e in conflicts}:
                held.add(key)  # §21: ingen falsk konsensus; initiativet väntar tills CEO har avgjort
                listed.discard(key)
            self._turn("cfo", ctx["day"], events, listed, held, record)
            self._turn("cro", ctx["day"], events, listed, held, record)
            self._turn("ceo", ctx["day"], events, listed, held, record)

        record["held"] = sorted(held)
        return self.sim.finish_day(ctx, frozenset(listed), record)

    # --- En agents tur ---------------------------------------------------------------------

    def _turn(self, role: str, day: int, events, listed: set, held: set, record: dict) -> None:
        agent = self._agent(role)
        if agent is None:
            record["rejected"].append({"role": role, "reason": f"ingen aktiv {role}"})
            return
        state = self._state(agent, day, events, listed, held, record)
        try:
            response = self._gateway.complete(agent.agent_id, self._request(agent, state))
        except PermissionDenied as exc:  # t.ex. nödstopp: inga modellanrop (SR-07)
            record["rejected"].append({"agent": agent.agent_id, "reason": f"modellanrop nekat: {exc.decision.reason}"})
            return
        except (NoProviderAvailable, SecretInPrompt) as exc:
            record["rejected"].append({"agent": agent.agent_id, "reason": f"ingen modell svarade: {exc}"})
            return
        actions, errors = parse_actions(response.text, self._initiatives)
        for error in errors:
            record["rejected"].append({"agent": agent.agent_id, "reason": error})
        if errors:
            self._system.audit.append(SYSTEM, "simulation.invalid_actions",
                                      {"agent_id": agent.agent_id, "day": day, "errors": list(errors)})
        for n, action in enumerate(actions, 1):
            if action.type not in ROLE_ACTIONS.get(role, ()):
                outcome = ("rejected", f"{role} får inte föreslå {action.type} (D-043)")
            else:
                outcome = self._execute(agent, action, day, n, listed, held, record)
            result = {"agent": agent.agent_id, "type": action.type, "initiative": action.get("initiative"),
                      "outcome": outcome[0], "reason": outcome[1]}
            record["actions"].append(result)
            self._system.audit.append(SYSTEM, "simulation.action", {"day": day, **result})

    def _execute(self, agent, action: Action, day: int, n: int, listed: set, held: set, record: dict):
        s = self._system
        decision = s.engine.check(agent.agent_id, TOOLS[action.type])
        if not decision.allowed:
            return "blocked", decision.reason
        key = action.get("initiative")
        if action.type == "list_for_sale":
            if key in held:
                return "blocked", "motstridiga bedömningar; väntar på CEO:s beslut (§21)"
            listed.add(key)
            return "done", "listat"
        if action.type == "pause_sale":
            listed.discard(key)
            return "done", action.get("reason")
        if action.type == "spend":
            return self._spend(agent, action, day, n)
        if action.type == "forecast":
            due = (date.fromisoformat(self.sim.clock.date) + timedelta(days=action.get("due_in_days"))).isoformat()
            try:
                f = s.forecasts.make(agent.agent_id, f"{action.get('metric')} för {key}, dag {day}",
                                     action.get("metric"), "SIM", action.get("expected"), due,
                                     action.get("low"), action.get("high"), initiative=key)
            except ForecastError as exc:
                return "blocked", str(exc)
            return "done", f"prognos {f.forecast_id}"
        if action.type == "proposal":
            record["proposals"].append({"agent": agent.agent_id, **action.fields})
            s.audit.append(agent.agent_id, "simulation.proposal", {"day": day, "initiative": key})
            return "done", "affärsförslag med alla 11 fält (§12)"
        if action.type == "assessment":
            record["assessments"].setdefault(key, {})[agent.role] = action.get("position")
            return "done", action.get("reason")
        if action.type == "decide":
            if action.get("choice") == "list":
                held.discard(key)
                listed.add(key)
            return "done", f"{action.get('choice')}: {action.get('reason')}"
        record["reports"].append({"agent": agent.agent_id, "title": action.get("title"), "hypothesis": action.get("text")})
        return "done", "rapport (hypotes, §29)"

    def _spend(self, agent, action: Action, day: int, n: int):
        s, initiative = self._system, self.sim.scenario.initiative(action.get("initiative"))
        request = SpendRequest(initiative.department, action.get("amount"), "SIM", initiative.key, Risk(action.get("risk")))
        check = s.budget.check(agent.agent_id, request)
        if not check.allowed:
            if not check.blocked and check.required_approvals and s.spend_approvals is not None:
                # F5, D-053: över tröskeln begärs en grundares godkännande; utgiften görs först efter ja
                a = s.spend_approvals.request(agent.agent_id, initiative.department, initiative.key,
                                              action.get("amount"), "SIM", action.get("purpose"),
                                              risk_class=request.risk_class, category=request.category)
                return "pending", f"väntar på en grundares godkännande (förfrågan {a.approval_id}, D-053)"
            return "blocked", check.describe()
        ref = f"sim-{self.sim.run_id}-d{day}-{agent.agent_id}-spend{n}"
        try:
            self._book_cost(ref, initiative, request, (f"external:{ref}",),
                            f"{action.get('purpose')} (föreslaget av {agent.agent_id})", agent.agent_id)
        except BudgetBlocked as exc:
            return "blocked", exc.check.describe()
        return "done", f"bokförd kostnad {action.get('amount')} SIM"

    def _approved_spends(self, day: int, record: dict) -> None:
        """Execute the original classified request; recheck authority and all gates."""
        s = self._system
        if s.spend_approvals is None:
            return
        keys = {i.key: i for i in self.sim.scenario.initiatives}
        for a in s.spend_approvals.approved_unused():
            initiative = keys.get(a.initiative)
            if initiative is None:
                continue
            outcome = {"approval_id": a.approval_id, "amount": a.amount_minor}
            authority = s.engine.check(a.requested_by, "sim.spend")
            if not authority.allowed or a.risk_class is None or a.category is None:
                outcome.update(outcome="blocked", reason=authority.reason if not authority.allowed else
                               "äldre godkännande saknar riskklass/kategori; begär ett nytt")
            else:
                request = SpendRequest(a.department, a.amount_minor, a.currency, a.initiative,
                                       Risk(a.risk_class), a.category)
                ref = f"sim-{self.sim.run_id}-d{day}-approval{a.approval_id}"
                try:
                    self._book_cost(ref, initiative, request, (f"external:{ref}",),
                                    f"{a.reason} (godkänd av {a.decided_by})", a.requested_by, a.approval_id)
                    outcome["outcome"] = "done"
                except BudgetBlocked as exc:
                    outcome.update(outcome="blocked", reason=exc.check.describe())
            record["approved_spends"].append(outcome)

    def _book_cost(self, ref, initiative, request, evidence, note, actor, approval_id=None):
        return self._system.budget.record_spend(actor, request, EntryDraft(
            ref, initiative.department, request.amount_minor, "SIM", EntryType.COST,
            initiative.key, Approval.NOT_REQUIRED, evidence, ref, Status.SETTLED, note),
            writer=SYSTEM, approval_id=approval_id)

    # --- Läge och förfrågan ----------------------------------------------------------------

    def _agent(self, role: str):
        return next((a for a in self._system.registry.agents() if a.role == role and a.state in ACTING_STATES), None)

    def _state(self, agent, day: int, events, listed: set, held: set, record: dict) -> dict:
        s = self._system
        entries = s.ledger.entries("SIM")
        history = self.sim.days()[-7:]
        stopped = self.sim._stopped_initiatives()
        spent, remaining = s.budget.usage(agent.department)
        initiatives = []
        for i in self.sim.scenario.initiatives:
            last7 = [d["initiatives"].get(i.key, {}) for d in history]
            initiatives.append({
                "initiative": i.key, "department": i.department, "price": i.price, "listed_from": i.listed_from,
                "listed": i.key in listed, "held": i.key in held, "stopped": i.key in stopped,
                "net_to_date": compute_result(entries, "SIM", initiative=i.key).net_minor,
                "revenue_last_7": sum(x.get("revenue_minor", 0) for x in last7),
                "net_last_7": sum(x.get("revenue_minor", 0) - x.get("refunds_minor", 0) - x.get("costs_minor", 0)
                                  for x in last7),
            })
        return {
            "role": agent.role, "agent": agent.agent_id, "day": day, "date": self.sim.clock.date,
            "initiatives": initiatives, "budget": {"department": agent.department, "spent": spent, "remaining": remaining},
            "kill_switch": s.kill.state().engaged, "protected_mode": s.protected.state().protected,
            "events": [{"kind": e.kind, "initiative": e.initiative, "note": e.note} for e in events],
            "assessments": record["assessments"], "allowed_actions": list(ROLE_ACTIONS.get(agent.role, ())),
        }

    def _request(self, agent, state: dict) -> ChatRequest:
        system_text = (f"Du är {agent.role} i avdelningen {agent.department} i ett simulerat företag (bara SIM). "
                       f"Tillåtna åtgärder för dig: {', '.join(ROLE_ACTIONS.get(agent.role, ()))}.\n" + schema_text())
        user_text = f"Dag {state['day']} ({state['date']}).\n{STATE_MARKER}\n" + json.dumps(state, ensure_ascii=False)
        return ChatRequest(messages=(Message("system", system_text), Message("user", user_text)),
                           data_class=self._data_class)
