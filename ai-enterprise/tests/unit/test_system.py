"""Tester för hela systemet ihopkopplat (Fas 6a). Verifierar D-041, SR-07, SR-08, SR-17, ER-13, ER-19, ER-20 och FR-15."""
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from aie import runtime
from aie.agents import AgentState, RegistryError
from aie.budget import Risk, SpendRequest
from aie.config import load_config
from aie.ledger import Approval, EntryDraft, EntryType, Status
from aie.memory import Database
from aie.monitoring import shutdown_logging
from aie.system import build_system
from .evidence import evidence

ROOT = Path(__file__).resolve().parents[2]
S = AgentState


class SystemCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.config = load_config(ROOT / "config")
        self.system = build_system(self.config, self.db, ROOT / "config")
        for agent_id, role, manager in (("ceo-1", "ceo", None), ("cfo-1", "cfo", None), ("cro-1", "cro", None),
                                        ("comp-1", "compliance", None), ("audit-1", "auditor", None),
                                        ("lead-1", "research_lead", "ceo-1"), ("res-1", "researcher", "lead-1")):
            self.add(agent_id, role, manager)

    def add(self, agent_id, role, manager=None):
        registry = self.system.registry
        registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            registry.transition(agent_id, state, "yorgo", "test")

    def approve_initiative(self, key, platform="testplattform"):
        """D-054, D-056: en godkänd plattform och ett godkänt initiativ i registret."""
        register = self.system.register
        source = [{"url": "file:test", "read_on": "2027-01-01"}]
        fees = {k: None for k in ("per_order_minor", "percent_bp", "per_listing_minor", "monthly_minor",
                                  "setup_minor", "payout_minor")} | {"currency": "SIM", "notes": "test"}
        data = {"name": "Test", "url": "file:test", "type": "product", "fees": fees, "currency": "SIM",
                "payment_terms": "x", "vat_responsibility": "x", "dac7": "x", "ai_rules": "x",
                "automation_rules": "x", "account_requirements": "x", "payout_terms": "x", "dependencies": [],
                "risks": [], "sources": source}
        item = {"platform": platform, "department": "research", "offering": "product", "description": "test",
                "price_minor": 100, "unit_cost_minor": 0, "currency": "SIM", "founder_hours_per_week": 0,
                "demand": {"visitors_per_day": 1, "conversion_bp": 1, "refund_bp": 0, "source": "antagande"}}
        for status in ("investigated", "reviewed"):
            register.record("robin", "platform", platform, status, data, "test")
            register.record("robin", "initiative", key, status, item, "test")
        a = register.assessments.record("robin", key, platform, item, data, evidence(), True)  # D-058
        register.assessments.approve("robin", a.assessment_id, "test")
        register.record("robin", "platform", platform, "approved", data, "test")
        register.record("robin", "initiative", key, "approved", item, "test")

    def book(self, key, department, entry_type, amount, status=Status.SETTLED, approval=Approval.NOT_REQUIRED):
        return self.system.ledger.record("robin", EntryDraft(key, department, amount, "SIM", entry_type, "etsy",
                                                             approval, ("decision:1",), status=status))


class TestWiring(SystemCase):
    def test_kill_switch_reaches_tools_spending_and_incidents(self):
        """Verifies D-041 och SR-07: nödstoppet når verktyg och utgifter och blir en incident, i det byggda systemet."""
        self.assertTrue(self.system.engine.check("res-1", "research.search").allowed)
        self.system.kill.engage("cro-1", "övning")
        self.assertFalse(self.system.engine.check("res-1", "research.search").allowed)
        check = self.system.budget.check("robin", SpendRequest("research", 100, "SIM", "etsy", Risk.LOW))
        self.assertTrue(any("SR-07" in r for r in check.blocked))
        self.assertIn("kill", [i.source.split(":")[0] for i in self.system.incidents.all()])

    def test_removal_guard_is_installed(self):
        """Verifies D-041 och SR-17: i det byggda systemet går avstängning bara genom ett ärende."""
        with self.assertRaises(RegistryError):
            self.system.registry.transition("res-1", S.SUSPENDED, "yorgo", "obekväm rapport")

    def test_protected_mode_and_tax_are_gates(self):
        """Verifies D-041, SR-08 och ER-20: skyddat driftläge och momsgränsen är spärrar i Authorization Engine."""
        gates = self.system.engine._gates
        self.assertIn(self.system.tax, gates)
        self.assertIn(self.system.protected, gates)
        self.book("s1", "research", EntryType.REVENUE, 12_000_000, approval=Approval.APPROVED)
        self.assertIn("ER-20", self.system.tax.tool_block_reason(None, "sales.create_listing"))
        self.system.protected.report_incident("audit-1", "misstänkt intrång")
        check = self.system.budget.check("robin", SpendRequest("research", 100, "SIM", "etsy", Risk.LOW))
        self.assertTrue(any("SR-08" in r for r in check.blocked))
        self.assertFalse(self.system.engine.check("res-1", "research.search").allowed)


class TestTick(SystemCase):
    def test_stoploss_waits_for_capital_then_trips_and_creates_incident(self):
        """Verifies D-041, ER-13 och FR-15: stop-loss mäts först när kapital finns, och en utlösning blir en incident."""
        self.assertEqual(self.system.tick(), [])
        self.assertEqual(self.system.stoploss.active(), ())
        self.book("cap", "finance", EntryType.CAPITAL_IN, 1_000_000, approval=Approval.APPROVED)
        self.book("k1", "research", EntryType.COST, 60_000, approval=Approval.APPROVED)  # över MAX_SINGLE_EXPERIMENT_LOSS
        self.assertEqual(self.system.tick(), [])
        self.assertTrue(self.system.stoploss.active())
        self.assertIn("stoploss", [i.source.split(":")[0] for i in self.system.incidents.all()])

    def test_reserved_tax_is_part_of_the_budget_check(self):
        """Verifies D-041 och ER-19: budgetmotorn i det byggda systemet räknar med den reserverade skatten."""
        self.book("cap", "finance", EntryType.CAPITAL_IN, 1_000_000, approval=Approval.APPROVED)
        unknown = self.system.budget.check("robin", SpendRequest("research", 100, "SIM", "etsy", Risk.LOW))
        self.assertFalse(unknown.allowed)  # D-054: initiativet finns inte i registret än
        # godkänns före första intäkten: med intäkter och utan D-059-gränserna i repots config stoppas nya initiativ (ER-02)
        self.approve_initiative("etsy")
        sale = self.book("s1", "research", EntryType.REVENUE, 10_000)
        self.system.tax.assign("robin", sale.entry_id, "partnership")
        check = self.system.budget.check("robin", SpendRequest("research", 100, "SIM", "etsy", Risk.LOW))
        self.assertTrue(check.allowed, check.describe())
        self.assertEqual(self.system.tax.reserved_minor(), 4_000)

    def test_a_failing_check_is_reported_and_others_still_run(self):
        """Verifies D-041 och §59: en kontroll som kraschar loggas, och de andra körs ändå."""
        calls = []
        self.system.incidents.sync = lambda: calls.append("sync")
        self.system.tax.check_vat = lambda: (_ for _ in ()).throw(RuntimeError("trasig"))
        errors = self.system.tick()
        self.assertEqual((len(errors), calls), (1, ["sync"]))
        self.assertIn("vat", errors[0])


class TestStartNeedsGates(unittest.TestCase):
    def test_start_refuses_without_the_config_for_its_gates(self):
        """Verifies D-041 och §59: saknas en konfigurationsfil för spärrarna startar systemet inte."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        config_dir = Path(tmp.name) / "config"
        shutil.copytree(ROOT / "config", config_dir)
        text = (config_dir / "system.toml").read_text(encoding="utf-8")
        text = text.replace('data_dir = "data"', f'data_dir = "{(Path(tmp.name) / "data").as_posix()}"')
        text = text.replace('log_dir = "logs"', f'log_dir = "{(Path(tmp.name) / "logs").as_posix()}"')
        (config_dir / "system.toml").write_text(text, encoding="utf-8")
        (config_dir / "tax.toml").unlink()
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = runtime.start(config_dir, poll_seconds=0.01)
        self.assertEqual(code, 1)
        self.assertIn("tax.toml", err.getvalue())
        self.assertIn("spärrar", err.getvalue())


if __name__ == "__main__":
    unittest.main()
