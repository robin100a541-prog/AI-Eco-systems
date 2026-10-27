"""En simuleringskörning: startkapital, dag för dag, omstart (Fas 6b-1, FR-20, §54, D-042).

**Bara simulerade pengar** (SR-11, §54 punkt 1). En körning kan bara startas när miljön är `sim` och
valutan är `SIM`. Ledgern avvisar dessutom `SIM` i prod. Det finns inga betalnings- eller nätverksanrop.

**Startkapital** (D-027 punkt 1). `START_CAPITAL` registreras som en godkänd `capital_in`-post med
underlaget `decision:D-042`. Det kan bara ske i en tom ledger. En databas har en körning. En ny körning
kräver en ny datamapp, så att två körningar aldrig blandas.

**En dag** (`advance()`):
1. Scenariots aktörshändelser för dagen utförs av en aktiv agent i den angivna rollen:
   `security_incident` anmäls till skyddat driftläge, och `kill_switch` aktiverar nödstoppet. Finns
   ingen sådan agent noteras det i dagen.
2. All försäljning pausas om nödstoppet är aktivt, om systemet är i skyddat driftläge eller om
   momsgränsen blockerar ny försäljning (ER-20). Ett initiativ pausas också när en aktiv stop-loss
   gäller det, dess departement eller hela företaget (§26: verksamheten stoppas eller begränsas).
3. Marknaden räknar fram dagens order. Varje order bokförs som fakta (D-024): en intäkt, en eventuell
   avgift (ER-23), en eventuell styckkostnad och en eventuell återbetalning. Varje post har ett eget
   externt ID, så att en dag som körs om efter en krasch aldrig bokförs två gånger (SR-12).
4. Intäkter och återbetalningar märks med scenariots skattespår (simulerat, D-010).
5. `System.tick()` körs: stop-loss, incidenter, momsgräns och prognoser.
6. Dagen sparas append-only med en sammanfattning (migration 26). Är dagen redan sparad hoppas den över.

Arbetscykeln med agenter (6b-2) bygger på `advance()`.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from ..agents import ACTING_STATES
from ..ledger import Approval, EntryDraft, EntryType, Status
from .market import InitiativeDay, Market, SimClock
from .scenario import ACTOR_EVENTS, Event, Initiative, Scenario, parse_scenario

SYSTEM = "system:simulation"
START_DECISION = "decision:D-042"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SimulationError(ValueError):
    pass


def stored_run(db) -> dict | None:
    """Den sparade körningen i databasen, eller None. Används före `build_system` vid omstart."""
    row = db.connection.execute(
        "SELECT run_id, scenario, seed, days, start_date, definition, created_by, at FROM simulation_runs"
    ).fetchone()
    if row is None:
        return None
    keys = ("run_id", "scenario", "seed", "days", "start_date", "definition", "created_by", "at")
    run = dict(zip(keys, row))
    run["definition"] = json.loads(run["definition"])
    return run


def require_sim(config) -> None:
    if config.system.environment != "sim" or config.risk.currency != "SIM":
        raise SimulationError("simuleringen körs bara i miljön sim med valutan SIM (SR-11, §54)")


class Simulation:
    def __init__(self, system, config, scenario: Scenario, run_id: int, clock: SimClock) -> None:
        self._system = system
        self._config = config
        self.scenario = scenario
        self.run_id = run_id
        self.clock = clock
        self._market = Market(scenario)
        limit = config.risk.human_approval_threshold
        self._threshold = limit.amount_minor if limit is not None else 0

    # --- Starta och återuppta --------------------------------------------------------------

    @classmethod
    def start(cls, system, config, scenario: Scenario, founder: str, clock: SimClock) -> "Simulation":
        require_sim(config)
        if founder not in config.system.founders:
            raise SimulationError("en simulering startas av en grundare")
        if stored_run(system.db) is not None:
            raise SimulationError("databasen har redan en körning; återuppta den eller använd en ny datamapp")
        if system.ledger.entries():
            raise SimulationError("ledgern är inte tom; en simulering startar i en egen datamapp")
        start = config.risk.start_capital
        if start is None or start.amount_minor <= 0:
            raise SimulationError("START_CAPITAL saknas i risk_limits.toml (ER-02)")
        definition = _definition(scenario)
        with system.db.transaction() as tx:
            run_id = tx.execute(
                "INSERT INTO simulation_runs (scenario, seed, days, start_date, definition, created_by, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (scenario.name, scenario.seed, scenario.days, scenario.start_date,
                 json.dumps(definition, ensure_ascii=False), founder, _now()),
            ).lastrowid
        clock.day = 1
        system.ledger.record(SYSTEM, EntryDraft(
            f"sim-{run_id}-start-capital", "finance", start.amount_minor, "SIM", EntryType.CAPITAL_IN,
            "simulerat startkapital", Approval.APPROVED, (START_DECISION,), f"sim-{run_id}-start-capital",
            Status.SETTLED, "simulerat startkapital (D-042, D-027 punkt 1)"))
        system.audit.append(founder, "simulation.started", {"run_id": run_id, "scenario": scenario.name,
                                                            "seed": scenario.seed, "days": scenario.days})
        return cls(system, config, scenario, run_id, clock)

    @classmethod
    def resume(cls, system, config, clock: SimClock) -> "Simulation":
        """Fortsätter körningen i databasen med den sparade scenariodefinitionen, inte filen."""
        require_sim(config)
        run = stored_run(system.db)
        if run is None:
            raise SimulationError("databasen har ingen körning att återuppta")
        departments = {m.department for m in system.permissions.roles.values()}
        scenario = parse_scenario(run["definition"], f"körning {run['run_id']}", departments,
                                  frozenset(config.system.founders))
        sim = cls(system, config, scenario, run["run_id"], clock)
        clock.day = max(sim.last_day, 1)
        system.audit.append(SYSTEM, "simulation.resumed", {"run_id": sim.run_id, "next_day": sim.last_day + 1})
        return sim

    # --- Dagar -----------------------------------------------------------------------------

    @property
    def last_day(self) -> int:
        row = self._system.db.connection.execute(
            "SELECT COALESCE(MAX(day), 0) FROM simulation_days WHERE run_id = ?", (self.run_id,)).fetchone()
        return row[0]

    @property
    def finished(self) -> bool:
        return self.last_day >= self.scenario.days

    def run(self, days: int | None = None) -> list[dict]:
        """Kör `days` dagar, eller resten av scenariot."""
        out = []
        target = self.scenario.days if days is None else min(self.scenario.days, self.last_day + days)
        while self.last_day < target:
            out.append(self.advance())
        return out

    def advance(self) -> dict:
        """En hel dag utan agenter: händelser, marknad, kontroller. Arbetscykeln (6b-2) delar upp den."""
        return self.finish_day(self.begin_day())

    def begin_day(self) -> dict:
        """Steg 1: nästa dag börjar och scenariots aktörshändelser utförs."""
        day = self.last_day + 1
        if day > self.scenario.days:
            raise SimulationError(f"scenariot har bara {self.scenario.days} dagar")
        self.clock.day = day
        events = [e for e in self.scenario.events if e.day == day]
        notes = [self._act(e) for e in events if e.kind in ACTOR_EVENTS]
        return {"day": day, "events": events, "event_notes": notes}

    def finish_day(self, ctx: dict, listed: frozenset[str] | None = None, extra: dict | None = None) -> dict:
        """Steg 2–6: spärrar, marknad, bokföring, kontroller och sparad dag.

        `listed`: initiativ som agenterna har listat. None betyder att alla säljer enligt scenariot (6b-1).
        `extra`: arbetscykelns del av sammanfattningen (agenternas åtgärder och resultat).
        """
        day, events, notes = ctx["day"], ctx["events"], ctx["event_notes"]
        s = self._system
        paused_reason = self._pause_reason()
        stopped = {} if paused_reason else self._stopped_initiatives()
        paused = frozenset(i.key for i in self.scenario.initiatives) if paused_reason else frozenset(stopped)
        unlisted = frozenset() if listed is None else frozenset(i.key for i in self.scenario.initiatives) - listed
        results = self._market.day(day, paused, unlisted)
        for result in results:
            self._book(day, self.scenario.initiative(result.initiative), result)
        tick_errors = s.tick()
        summary = {
            "day": day, "date": self.clock.date,
            "initiatives": {r.initiative: {"orders": len(r.orders), "revenue_minor": r.revenue,
                                           "refunds_minor": r.refunds, "costs_minor": r.costs,
                                           "notes": list(r.notes)} for r in results},
            "paused": paused_reason, "stopped": stopped, "events": [asdict(e) for e in events], "event_notes": notes,
            "tick_errors": tick_errors,
            "listed": None if listed is None else sorted(listed),
            **(extra or {}),
        }
        with s.db.transaction() as tx:
            tx.execute("INSERT INTO simulation_days (run_id, day, date, summary, at) VALUES (?, ?, ?, ?, ?)",
                       (self.run_id, day, self.clock.date, json.dumps(summary, ensure_ascii=False), _now()))
        s.audit.append(SYSTEM, "simulation.day", {"run_id": self.run_id, "day": day,
                                                  "orders": sum(len(r.orders) for r in results),
                                                  "paused": paused_reason})
        return summary

    def days(self) -> tuple[dict, ...]:
        return tuple(json.loads(r[0]) for r in self._system.db.connection.execute(
            "SELECT summary FROM simulation_days WHERE run_id = ? ORDER BY day", (self.run_id,)))

    # --- Internt ---------------------------------------------------------------------------

    def _act(self, event: Event) -> str:
        s = self._system
        agent = next((a for a in s.registry.agents() if a.role == event.role and a.state in ACTING_STATES), None)
        if agent is None:
            return f"dag {event.day}: {event.kind} kräver en aktiv {event.role}; ingen fanns"
        note = event.note or f"simulerad händelse dag {event.day}"
        if event.kind == "security_incident":
            s.protected.report_incident(agent.agent_id, note)
        elif event.kind == "kill_switch":
            s.kill.engage(agent.agent_id, note)
        return f"dag {event.day}: {event.kind} av {agent.agent_id}"

    def _pause_reason(self) -> str | None:
        s = self._system
        kill = s.kill.state()
        if kill.engaged:
            return f"nödstopp aktivt sedan {kill.engaged_at}: inga nya transaktioner (SR-07)"
        mode = s.protected.state()
        if mode.protected:
            return f"skyddat driftläge sedan {mode.since}: ingen ny försäljning (SR-08)"
        vat = s.tax.check_vat(int(self.clock.date[:4]))
        if vat.blocks_sales:
            return f"momsgränsen är nådd för {vat.year}; ny försäljning väntar på grundarnas beslut (ER-20)"
        return None

    def _stopped_initiatives(self) -> dict[str, str]:
        """Initiativ som en aktiv stop-loss gäller, med skälet (ER-13, §26)."""
        out: dict[str, str] = {}
        for trip in self._system.stoploss.active():
            for i in self.scenario.initiatives:
                hit = ((trip.scope_kind == "initiative" and trip.scope_value == i.key)
                       or (trip.scope_kind == "department" and trip.scope_value == i.department)
                       or trip.scope_kind == "company")
                if hit and i.key not in out:
                    out[i.key] = f"stop-loss {trip.trip_id}: {trip.limit_name} ({trip.scope_kind} {trip.scope_value})"
        return out

    def _book(self, day: int, initiative: Initiative, result: InitiativeDay) -> None:
        for order in result.orders:
            ref = f"sim-{self.run_id}-d{day}-{initiative.key}-o{order.number}"
            sale = self._record(f"{ref}-sale", initiative, order.price, EntryType.REVENUE, ref)
            self._track(sale.entry_id, initiative)
            if order.fee:
                self._record(f"{ref}-fee", initiative, order.fee, EntryType.FEE, ref)
            if order.unit_cost:
                self._record(f"{ref}-cost", initiative, order.unit_cost, EntryType.COST, ref)
            if order.refunded:
                refund = self._record(f"{ref}-refund", initiative, order.price, EntryType.REFUND, ref)
                self._track(refund.entry_id, initiative)

    def _record(self, key: str, initiative: Initiative, amount: int, entry_type: EntryType, ref: str):
        evidence: tuple[str, ...] = (f"external:{ref}",)
        approval = Approval.NOT_REQUIRED
        if amount > self._threshold:
            approval, evidence = Approval.APPROVED, (START_DECISION, *evidence)
        return self._system.ledger.record(SYSTEM, EntryDraft(
            key, initiative.department, amount, "SIM", entry_type, initiative.key, approval, evidence, key,
            Status.SETTLED, "simulerad order (D-042)"))

    def _track(self, entry_id: int, initiative: Initiative) -> None:
        tax = self._system.tax
        if tax.assignment(entry_id) is None:
            tax.assign(SYSTEM, entry_id, initiative.track, owner=initiative.owner,
                       note="simulerat skattespår enligt scenariot (D-010 är öppet)")


def _definition(scenario: Scenario) -> dict:
    """Scenariot som det sparas i körningen, i samma form som TOML-filen."""
    initiatives = []
    for i in scenario.initiatives:
        item = {k: v for k, v in asdict(i).items() if v is not None}
        initiatives.append(item)
    events = [{k: v for k, v in asdict(e).items() if v not in (None, "")} for e in scenario.events]
    return {"config_version": 1, "name": scenario.name, "description": scenario.description, "seed": scenario.seed,
            "days": scenario.days, "start_date": scenario.start_date, "initiatives": initiatives, "events": events}
