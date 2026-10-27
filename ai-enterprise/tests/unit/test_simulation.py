"""Tester för affärssimuleringens grund (Fas 6b-1). Verifierar FR-20, §54, SR-11, SR-12, ER-13, ER-20, D-042 och FR-03."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentState
from aie.authorization import load_permissions
from aie.config import ConfigError, load_config
from aie.ledger import EntryType, compute_result
from aie.memory import Database
from aie.simulation import (EVENT_KINDS, Market, SimClock, Simulation, SimulationError, available, load_scenario,
                            parse_scenario)
from aie.system import build_system

from .fixture_config import TEST_CONFIG

ROOT = Path(__file__).resolve().parents[2]
CONFIG = TEST_CONFIG  # låsta gränsvärden (D-047); scenarierna är repots egna
FOUNDERS = frozenset({"robin", "yorgo"})
DEPARTMENTS = {m.department for m in load_permissions(CONFIG).roles.values()}
ORG = (("ceo-1", "ceo", None), ("cfo-1", "cfo", None), ("cro-1", "cro", None), ("comp-1", "compliance", None),
       ("audit-1", "auditor", None), ("lead-1", "research_lead", "ceo-1"))


def scenario(name):
    return load_scenario(CONFIG, name, DEPARTMENTS, FOUNDERS)


class SimCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config = load_config(CONFIG)

    def open(self, start_date="2027-01-01"):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.clock = SimClock(start_date)
        self.system = build_system(self.config, self.db, CONFIG, clock=self.clock)
        return self.system

    def start(self, name, org=True):
        sc = scenario(name)
        system = self.open(sc.start_date)
        if org:
            for agent_id, role, manager in ORG:
                system.registry.register(agent_id, role, manager, "yorgo", "test")
                for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                    system.registry.transition(agent_id, state, "yorgo", "test")
        return Simulation.start(system, self.config, sc, "yorgo", self.clock)


class TestScenarios(unittest.TestCase):
    def test_all_shipped_scenarios_are_valid(self):
        """Verifies FR-20 och §54: scenarierna täcker normal marknad, förlust, budget, konflikt, moms, intrång och nödstopp."""
        self.assertEqual(set(available(CONFIG)),
                         {"normal", "loss", "budget_overrun", "conflict", "vat", "intrusion", "kill"})
        kinds = {e.kind for name in available(CONFIG) for e in scenario(name).events}
        self.assertLessEqual(kinds, EVENT_KINDS)

    def test_invalid_scenarios_are_refused(self):
        """Verifies D-042: fel i ett scenario samlas och avvisas; belopp är heltal (D-006)."""
        base = {"config_version": 1, "name": "x", "description": "x", "seed": "s", "days": 5,
                "start_date": "2027-01-01",
                "initiatives": [{"key": "a", "department": "research", "track": "partnership", "price": 100,
                                 "unit_cost": 0, "fee_fixed": 0, "fee_bp": 0, "visitors": 1, "conversion_bp": 1,
                                 "refund_bp": 0}]}
        parse_scenario(base, "ok", DEPARTMENTS, FOUNDERS)
        broken = (
            {"days": 0}, {"start_date": "snart"},
            {"initiatives": [{**base["initiatives"][0], "price": 9.5}]},
            {"initiatives": [{**base["initiatives"][0], "department": "marketing"}]},
            {"initiatives": [{**base["initiatives"][0], "track": "hobby"}]},  # owner saknas
            {"initiatives": [{**base["initiatives"][0], "conversion_bp": 20_000}]},
            {"events": [{"day": 9, "kind": "platform_outage", "initiative": "a"}]},
            {"events": [{"day": 1, "kind": "meteor"}]},
            {"events": [{"day": 1, "kind": "kill_switch"}]},  # role saknas
        )
        for change in broken:
            with self.subTest(change=change), self.assertRaises(ConfigError):
                parse_scenario({**base, **change}, "fel", DEPARTMENTS, FOUNDERS)


class TestMarket(unittest.TestCase):
    def test_market_is_deterministic_and_integer(self):
        """Verifies D-042: samma scenario och dag ger samma order, i vilken ordning dagarna än räknas."""
        sc = scenario("normal")
        forward = [Market(sc).day(d) for d in range(1, 11)]
        backward = [Market(sc).day(d) for d in range(10, 0, -1)][::-1]
        self.assertEqual(forward, backward)
        self.assertTrue(any(r.orders for day in forward for r in day))
        order = next(o for day in forward for r in day for o in r.orders)
        self.assertEqual(order.fee, 570 + -(-4_900 * 1_050 // 10_000))  # 1 085, avrundat uppåt
        self.assertTrue(all(isinstance(o.price, int) for day in forward for r in day for o in r.orders))

    def test_events_change_the_market(self):
        """Verifies FR-20: plattformsavbrott stoppar försäljningen, efterfrågechock och kostnadsökning skalar."""
        sc = scenario("normal")
        self.assertEqual(Market(sc).day(12)[0].orders, ())
        self.assertIn("plattformen ligger nere", Market(sc).day(12)[0].notes)
        self.assertEqual(Market(sc).day(3)[1].orders, ())  # gumroad säljer från dag 5
        shocked = replace(sc, events=(replace(sc.events[0], kind="demand_shock", day=1, until=30, factor_bp=0),))
        self.assertTrue(all(not Market(shocked).day(d)[0].orders for d in range(1, 31)))
        self.assertEqual(Market(sc).day(1, paused=frozenset({"etsy-mallar"}))[0].orders, ())


class TestRun(SimCase):
    def test_start_capital_and_only_sim(self):
        """Verifies §54 punkt 1, SR-11 och D-042: startkapitalet registreras en gång, bara i sim och av en grundare."""
        sim = self.start("normal")
        (capital,) = [e for e in self.system.ledger.entries() if e.entry_type is EntryType.CAPITAL_IN]
        self.assertEqual((capital.amount_minor, capital.currency, capital.recorded_by),
                         (1_000_000, "SIM", "system:simulation"))
        with self.assertRaises(SimulationError):
            Simulation.start(self.system, self.config, sim.scenario, "yorgo", self.clock)  # en körning per databas
        prod = replace(self.config, system=replace(self.config.system, environment="prod"))
        with self.assertRaises(SimulationError):
            Simulation.start(self.system, prod, sim.scenario, "yorgo", self.clock)

    def test_only_founders_start_and_empty_ledger(self):
        """Verifies D-042: en agent kan inte starta en simulering."""
        sc = scenario("normal")
        system = self.open(sc.start_date)
        with self.assertRaises(SimulationError):
            Simulation.start(system, self.config, sc, "ceo-1", self.clock)

    def test_days_book_orders_with_simulated_dates_and_tax_tracks(self):
        """Verifies FR-20, ER-18 och ER-23: varje order blir intäkt och avgift med simulerat datum och skattespår."""
        sim = self.start("normal")
        days = sim.run(5)
        self.assertEqual([d["date"] for d in days], [f"2027-01-0{n}" for n in range(1, 6)])
        sales = [e for e in self.system.ledger.entries() if e.entry_type is EntryType.REVENUE]
        fees = [e for e in self.system.ledger.entries() if e.entry_type is EntryType.FEE]
        self.assertEqual(len(sales), len(fees))
        self.assertEqual(len(sales), sum(v["orders"] for d in days for v in d["initiatives"].values()))
        self.assertTrue(all(e.recorded_at.startswith("2027-01-0") for e in sales))
        self.assertTrue(all(self.system.tax.assignment(e.entry_id).track == "partnership" for e in sales))
        self.assertGreater(self.system.tax.reserved_minor(), 0)

    def test_restart_continues_without_losing_or_duplicating_history(self):
        """Verifies §54 punkt 5, FR-03 och SR-12: efter omstart fortsätter körningen; inget går förlorat eller dubbleras."""
        sim = self.start("normal")
        sim.run(3)
        before = [e.entry_id for e in self.system.ledger.entries()]
        self.db.close()
        system = self.open()
        sim = Simulation.resume(system, self.config, self.clock)
        self.assertEqual(sim.last_day, 3)
        sim._book(3, sim.scenario.initiatives[0], Market(sim.scenario).day(3)[0])  # dag 3 körs om efter en krasch
        self.assertEqual([e.entry_id for e in system.ledger.entries()], before)  # samma externa ID ⇒ inga dubbletter
        sim.run(2)
        self.assertEqual(sim.last_day, 5)
        self.assertTrue(system.audit.verify().ok)
        self.assertEqual([d["day"] for d in sim.days()], [1, 2, 3, 4, 5])


class TestGatesDuringRuns(SimCase):
    def test_loss_initiative_trips_stoploss_and_is_paused(self):
        """Verifies §54 punkt 2–3 och ER-13: ett förlustbringande initiativ löser ut stop-loss, pausas och blir en incident."""
        sim = self.start("loss")
        days = sim.run()
        trips = {(t.scope_kind, t.scope_value) for t in self.system.stoploss.active()}
        # Med budgets.toml når departementsbudgeten (50 000) fram före förlustgränsen per initiativ (50 000).
        self.assertTrue(trips & {("initiative", "tryckta-affischer"), ("department", "research")})
        stopped_day = next(d["day"] for d in days if "tryckta-affischer" in d["stopped"])
        after = [d for d in days if d["day"] > stopped_day]
        self.assertTrue(after)
        self.assertTrue(all(d["initiatives"]["tryckta-affischer"]["orders"] == 0 for d in after))
        loss = compute_result(self.system.ledger.entries("SIM"), "SIM", initiative="tryckta-affischer").net_minor
        self.assertLess(loss, 0)
        self.assertIn("stoploss", [i.source.split(":")[0] for i in self.system.incidents.all()])

    def test_kill_switch_mid_run_stops_sales_and_deletes_nothing(self):
        """Verifies SR-07 och §54 punkt 3: nödstopp dag 5 stoppar all försäljning; inget raderas."""
        sim = self.start("kill")
        days = sim.run(4)
        entries = len(self.system.ledger.entries())
        days += sim.run()
        self.assertIn("kill_switch av cro-1", days[4]["event_notes"][0])
        self.assertTrue(all(d["paused"] and "SR-07" in d["paused"] for d in days[4:]))
        self.assertEqual(len(self.system.ledger.entries()), entries)
        self.assertIn("kill", [i.source.split(":")[0] for i in self.system.incidents.all()])

    def test_intrusion_puts_the_system_in_protected_mode(self):
        """Verifies SR-08: en anmäld säkerhetsincident dag 6 ger skyddat driftläge och pausad försäljning."""
        sim = self.start("intrusion")
        days = sim.run()
        self.assertTrue(self.system.protected.state().protected)
        self.assertTrue(all("SR-08" in d["paused"] for d in days[5:]))
        self.assertTrue(all(d["paused"] is None for d in days[:5]))

    def test_actor_event_without_agent_is_noted(self):
        """Verifies D-042: en händelse som kräver en roll utan aktiv agent utförs inte, men det syns i dagen."""
        sim = self.start("kill", org=False)
        days = sim.run(5)
        self.assertIn("ingen fanns", days[4]["event_notes"][0])

    def test_vat_limit_pauses_sales_until_both_founders_vote(self):
        """Verifies ER-20: momsgränsen pausar ny försäljning tills båda grundarna har beslutat."""
        sim = self.start("vat")
        days = sim.run()
        paused = [d for d in days if d["paused"] and "ER-20" in d["paused"]]
        self.assertTrue(paused)
        self.assertEqual(self.system.tax.vat_status(2027).level, "limit")
        self.system.tax.vat_vote("robin", 2027, "momsregistrerad (simulerat)")
        self.system.tax.vat_vote("yorgo", 2027, "momsregistrerad (simulerat)")
        self.assertIsNone(sim._pause_reason())


if __name__ == "__main__":
    unittest.main()
