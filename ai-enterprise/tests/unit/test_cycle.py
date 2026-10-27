"""Tester för åtgärdsprotokollet, arbetscykeln och `aie simulate` (Fas 6b-2). Verifierar D-043, D-044, FR-20,
FR-23, §12, §20, §21, ER-03, ER-20, SR-07, DR-13 och FR-03."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from aie.authorization import load_permissions
from aie.config import load_config
from aie.ledger import EntryType
from aie.llm.gateway import LLMGateway
from aie.llm.providers import RuleProvider
from aie.llm.router import ProviderRouter, QuotaLedger, Slot
from aie.memory import Database
from aie.monitoring import shutdown_logging
from aie.simulation import (MAX_ACTIONS, PROPOSAL_FIELDS, Action, ScriptedPolicy, SimClock, Simulation, WorkCycle,
                            build_gateway, ensure_org, load_scenario, parse_actions)
from aie.simulation.cli import simulate
from aie.system import build_system

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
FOUNDERS = frozenset({"robin", "yorgo"})
DEPARTMENTS = {m.department for m in load_permissions(CONFIG).roles.values()}
KEYS = frozenset({"etsy-mallar"})
PROPOSAL = {"type": "proposal", "initiative": "etsy-mallar", "customer_problem": "p", "solution": "s",
            "target_group": "t", "demand_evidence": "d", "expected_revenue": 100, "costs": 10, "expected_net": 90,
            "max_loss": 50, "time_to_first_revenue": "1 vecka", "test_method": "m", "continue_or_stop": "c"}


class TestActions(unittest.TestCase):
    def test_valid_actions_and_json_inside_text(self):
        """Verifies D-043: giltiga åtgärder tas emot, även när modellen skriver text runt JSON."""
        text = 'Här är mitt förslag: {"actions": [{"type": "list_for_sale", "initiative": "etsy-mallar"}]} tack'
        actions, errors = parse_actions(text, KEYS)
        self.assertEqual((actions, errors), ((Action("list_for_sale", {"initiative": "etsy-mallar"}),), ()))

    def test_invalid_answers_are_refused_and_never_executed(self):
        """Verifies D-043 och D-006: ogiltig JSON, okända typer, flyttal, critical och okända initiativ avvisas."""
        self.assertEqual(parse_actions("köp allt", KEYS)[0], ())
        bad = [{"type": "transfer", "amount": 1},
               {"type": "spend", "initiative": "etsy-mallar", "amount": 9.5, "purpose": "x", "risk": "low"},
               {"type": "spend", "initiative": "etsy-mallar", "amount": 100, "purpose": "x", "risk": "critical"},
               {"type": "list_for_sale", "initiative": "okänt"},
               {"type": "forecast", "initiative": "etsy-mallar", "metric": "mood", "expected": 1, "due_in_days": 7}]
        actions, errors = parse_actions(json.dumps({"actions": bad}), KEYS)
        self.assertEqual((actions, len(errors)), ((), 5))

    def test_proposal_needs_all_eleven_fields_of_section_12(self):
        """Verifies FR-23 och §12: ett affärsförslag utan alla 11 fält avvisas."""
        self.assertEqual(len(PROPOSAL_FIELDS), 11)
        self.assertEqual(len(parse_actions(json.dumps({"actions": [PROPOSAL]}), KEYS)[0]), 1)
        for field in PROPOSAL_FIELDS:
            broken = {k: v for k, v in PROPOSAL.items() if k != field}
            with self.subTest(field=field):
                self.assertEqual(parse_actions(json.dumps({"actions": [broken]}), KEYS)[0], ())

    def test_at_most_max_actions(self):
        """Verifies D-043: högst MAX_ACTIONS åtgärder per agent och dag."""
        many = [{"type": "list_for_sale", "initiative": "etsy-mallar"}] * (MAX_ACTIONS + 5)
        actions, errors = parse_actions(json.dumps({"actions": many}), KEYS)
        self.assertEqual(len(actions), MAX_ACTIONS)
        self.assertTrue(errors)


class CycleCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config = load_config(CONFIG)

    def build(self, start_date="2027-01-01"):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.clock = SimClock(start_date)
        self.system = build_system(self.config, self.db, CONFIG, clock=self.clock)
        return self.system

    def cycle(self, name, responder=None):
        sc = load_scenario(CONFIG, name, DEPARTMENTS, FOUNDERS)
        system = self.build(sc.start_date)
        ensure_org(system.registry, "yorgo")
        self.sim = Simulation.start(system, self.config, sc, "yorgo", self.clock)
        if responder is None:
            gateway = build_gateway(system)
        else:
            router = ProviderRouter((Slot(RuleProvider("test", responder), 10_000, 10_000_000),),
                                    QuotaLedger(system.db), system.audit)
            gateway = LLMGateway(router, system.engine, system.audit)
        return WorkCycle(self.sim, system, gateway)

    @staticmethod
    def actions(days, **match):
        return [a for d in days for a in d["actions"] if all(a.get(k) == v for k, v in match.items())]


class TestCycle(CycleCase):
    def test_agents_list_forecast_propose_and_sell(self):
        """Verifies FR-20, FR-16 och FR-23: agenterna listar, prognostiserar och föreslår, och marknaden säljer det listade."""
        days = self.cycle("normal").run(15)
        self.assertTrue(self.actions(days, type="list_for_sale", outcome="done"))
        self.assertEqual(len(days[0]["proposals"]), 1)
        self.assertTrue(any(f.outcome is not None for f in self.system.forecasts.all()))  # jämförd med ledgern
        self.assertGreater(sum(d["initiatives"]["etsy-mallar"]["orders"] for d in days), 0)
        self.assertEqual(days[1]["initiatives"]["gumroad-guider"]["notes"], ["inte listat till försäljning"])

    def test_overspend_is_blocked_by_the_budget_engine(self):
        """Verifies ER-03 och D-043: en utgift över budgeten nekas; en utgift inom budgeten bokförs."""
        days = self.cycle("budget_overrun").run()
        blocked = self.actions(days, type="spend", outcome="blocked")
        self.assertEqual(len(blocked), 2)
        self.assertIn("budgeten överskrids", blocked[0]["reason"])
        (done,) = self.actions(days, type="spend", outcome="done")
        costs = [e for e in self.system.ledger.entries() if e.entry_type is EntryType.COST]
        self.assertEqual([(e.amount_minor, e.recorded_by) for e in costs], [(2_000, "system:simulation")])

    def test_conflicting_assessments_are_documented_and_ceo_decides(self):
        """Verifies §21 och §20 steg 3: CFO och CRO är oense, ingen falsk konsensus, CEO väljer det säkrare."""
        days = self.cycle("conflict").run(8)
        self.assertEqual(days[3]["assessments"], {"fiverr-texter": {"cfo": "for", "cro": "against"}})
        (decision,) = self.actions(days, type="decide")
        self.assertTrue(decision["reason"].startswith("hold"))
        self.assertTrue(all(d["initiatives"]["fiverr-texter"]["orders"] == 0 for d in days[3:]))
        self.assertIn("fiverr-texter", days[-1]["held"])

    def test_a_role_cannot_take_actions_outside_its_list(self):
        """Verifies D-043 och D-044: en arbetsagent som försöker spendera nekas, även om svaret är giltigt."""
        def responder(request):
            return json.dumps({"actions": [{"type": "spend", "initiative": "etsy-mallar", "amount": 100,
                                            "purpose": "x", "risk": "low"}]})
        days = self.cycle("normal", responder).run(1)
        outcomes = {(a["agent"], a["outcome"]) for a in days[0]["actions"]}
        self.assertIn(("res-1", "rejected"), outcomes)  # inte i rollens lista
        self.assertIn(("lead-1", "done"), outcomes)

    def test_invalid_model_output_is_logged_and_nothing_happens(self):
        """Verifies D-043: ett svar som inte är JSON loggas som avvisat och ingenting genomförs."""
        days = self.cycle("normal", lambda request: "jag köper reklam för 1 000 000").run(2)
        self.assertEqual([a for d in days for a in d["actions"]], [])
        self.assertTrue(all(d["rejected"] for d in days))
        self.assertIn("simulation.invalid_actions", [e.action for e in self.system.audit.entries()])
        self.assertFalse([e for e in self.system.ledger.entries() if e.entry_type is EntryType.COST])

    def test_kill_switch_stops_model_calls_and_actions(self):
        """Verifies SR-07: efter nödstoppet görs inga modellanrop och inga åtgärder."""
        days = self.cycle("kill").run()
        after = days[4:]
        self.assertTrue(all(not d["actions"] for d in after))
        self.assertTrue(all(any("modellanrop nekat" in r["reason"] for r in d["rejected"]) for d in after))

    def test_vat_gate_blocks_listing(self):
        """Verifies ER-20 och D-044: när momsgränsen är nådd nekas sales.list."""
        cycle = self.cycle("vat")
        cycle.run()
        lead = self.system.registry.get("lead-1")
        outcome = cycle._execute(lead, Action("list_for_sale", {"initiative": "kurspaket"}), 41, 1, set(), set(), {})
        self.assertEqual(outcome[0], "blocked")
        self.assertIn("ER-20", outcome[1])

    def test_internal_state_only_goes_to_local_providers(self):
        """Verifies DR-13: läget skickas som internal-data, så externa leverantörer kan aldrig ta emot det."""
        cycle = self.cycle("normal")
        agent = self.system.registry.get("lead-1")
        request = cycle._request(agent, cycle._state(agent, 1, [], set(), set(), {"assessments": {}}))
        self.assertEqual(request.data_class.value, "internal")
        self.assertTrue(all(not s.provider.external for s in build_gateway(self.system)._router._slots))

    def test_listing_survives_restart(self):
        """Verifies §54 punkt 5 och FR-03: efter omstart fortsätter cykeln med samma listning."""
        self.cycle("normal").run(3)
        self.db.close()
        system = self.build()
        sim = Simulation.resume(system, self.config, self.clock)
        days = WorkCycle(sim, system, build_gateway(system)).run(1)
        self.assertIn("etsy-mallar", days[0]["listed"])
        self.assertFalse(self.actions(days, type="list_for_sale", initiative="etsy-mallar"))


class TestCommand(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        self.dir = Path(tmp.name)
        self.config_dir = self.dir / "config"
        shutil.copytree(CONFIG, self.config_dir)
        text = (self.config_dir / "system.toml").read_text(encoding="utf-8")
        text = text.replace('data_dir = "data"', f'data_dir = "{(self.dir / "data").as_posix()}"')
        text = text.replace('log_dir = "logs"', f'log_dir = "{(self.dir / "logs").as_posix()}"')
        (self.config_dir / "system.toml").write_text(text, encoding="utf-8")

    def run_cli(self, *args, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = simulate(self.config_dir, *args, **kwargs)
        shutdown_logging()
        return code, out.getvalue(), err.getvalue()

    def test_start_status_resume(self):
        """Verifies D-043: start, status och resume via kommandot, med SIM och intakt revisionslogg."""
        code, out, _ = self.run_cli("start", "normal", "yorgo", 3)
        self.assertEqual(code, 0)
        self.assertIn("bara SIM", out)
        self.assertIn("revisionslogg OK", out)
        self.assertEqual(out.count("\ndag "), 3)
        code, out, _ = self.run_cli("status")
        self.assertIn("Dag 3 av 30", out)
        code, out, _ = self.run_cli("resume", days=2)
        self.assertEqual(code, 0)
        self.assertIn("Klar till dag 5", out)
        code, _, err = self.run_cli("start", "normal", "yorgo", 1)
        self.assertEqual(code, 1)
        self.assertIn("redan en körning", err)

    def test_unknown_scenario_is_refused(self):
        """Verifies D-042: ett scenario som inte finns ger kod 1 och ett läsbart fel."""
        code, _, err = self.run_cli("start", "finns-inte", "yorgo", 1)
        self.assertEqual(code, 1)
        self.assertIn("scenariot finns inte", err)


if __name__ == "__main__":
    unittest.main()
