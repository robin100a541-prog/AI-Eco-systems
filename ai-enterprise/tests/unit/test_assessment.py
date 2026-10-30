"""Tester för bedömning före start och automatisk paus (PR 6, D-058). Verifierar D-058, D-048, §54, SR-11 och FR-15."""
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.config import load_config
from aie.evaluation import IncidentLog
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.registry import SYSTEM, AssessmentError, Register, RegistryError, check_active
from aie.simulation import SimulationError
from aie.simulation.assessment import (
    DISCLAIMER,
    assess_initiative,
    load_assessment_rules,
    scenario_inputs,
)
from aie.system import build_system

from .fixture_config import TEST_CONFIG
from .evidence import evidence

FOUNDERS = frozenset({"robin", "yorgo"})
FEES = {"per_order_minor": 30, "percent_bp": 500, "per_listing_minor": None, "monthly_minor": None,
        "setup_minor": None, "payout_minor": None, "currency": "USD", "notes": "test"}
PLATFORM = {"name": "Plattform A", "url": "https://example.com", "type": "product", "fees": FEES, "currency": "USD",
            "payment_terms": "okänt", "vat_responsibility": "okänt", "dac7": "okänt", "ai_rules": "okänt",
            "automation_rules": "okänt", "account_requirements": "okänt", "payout_terms": "okänt",
            "dependencies": [], "risks": [], "sources": [{"url": "https://example.com", "read_on": "2026-10-28"}]}
STRONG = {"platform": "plattform-a", "department": "research", "offering": "product", "description": "mallar",
          "price_minor": 19_900, "unit_cost_minor": 0, "currency": "SIM", "founder_hours_per_week": 0,
          "demand": {"visitors_per_day": 100, "conversion_bp": 500, "refund_bp": 100, "source": "antagande"}}
CAPITAL_BUDGETS = """config_version = 1
mode = "capital"
[departments.research]
share = 40
max_commitment = 20_000
risk_room = "medium"
purpose = "försök"
"""
QUICK = """config_version = 1
[readiness]
min_runs = 3
min_days = 30
recent_days = 10
min_margin_percent = 10
max_drawdown_percent = 20
first_real_investment = 50_000
next_real_investment = 100_000
[assessment]
usd_cent_in_sim_minor = 11
unknown_percent_fee_bp = 500
unknown_fixed_fee_minor = 500
founder_hour_value_minor = 10_000
pessimistic_demand_bp = 2_500
pessimistic_refund_factor = 2
pause_after_days = 14
"""


class AssessCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config_dir = self.dir / "config"
        shutil.copytree(TEST_CONFIG, self.config_dir)
        (self.config_dir / "simulation.toml").write_text(QUICK, encoding="utf-8")
        # Kapitalbaserade budgetar (D-047), som i repots konfiguration: avgifter belastar inte departementet.
        (self.config_dir / "budgets.toml").write_text(CAPITAL_BUDGETS, encoding="utf-8")
        self.config = load_config(self.config_dir)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.system = build_system(self.config, self.db, self.config_dir)
        self.register = self.system.register

    def prepare(self, initiative=STRONG, key="mallar"):
        for status in ("investigated", "reviewed"):
            if self.register.get("platform", "plattform-a") is None or status == "reviewed":
                self.register.record("yorgo", "platform", "plattform-a", status, PLATFORM, "test")
            self.register.record("yorgo", "initiative", key, status, initiative, "test")


class TestAssessment(AssessCase):
    def test_a_strong_initiative_is_ready_and_can_then_be_approved(self):
        """Verifies D-058 och D-048: normalt och pessimistiskt scenario med vinst efter allt ger redo; först då godkänns initiativet."""
        self.prepare()
        with self.assertRaises(RegistryError):
            self.register.set_status("yorgo", "initiative", "mallar", "approved", "ingen bedömning än")
        a = assess_initiative(self.config, self.config_dir, self.register, "mallar", "yorgo")
        self.assertTrue(a.ready, a.result["reasons"])
        self.assertEqual(set(a.result["scenarios"]), {"normal", "pessimistic", "zero_sales"})
        self.assertEqual(a.result["disclaimer"], DISCLAIMER)
        self.assertEqual(len(a.result["scenarios"]["pessimistic"]["runs"]), 3)
        self.register.assessments.approve("yorgo", a.assessment_id, "antagandena är rimliga")
        self.register.set_status("yorgo", "platform", "plattform-a", "approved", "bedömd")
        self.register.set_status("yorgo", "initiative", "mallar", "approved", "bedömd")
        self.assertIsNone(self.register.spend_block_reason("research", "mallar"))

    def test_founder_time_and_low_demand_make_it_not_ready(self):
        """Verifies D-058: grundarnas tid räknas som kostnad, och pessimistisk förlust ger inte redo; det kan inte godkännas."""
        weak = STRONG | {"founder_hours_per_week": 10,
                         "demand": {"visitors_per_day": 40, "conversion_bp": 300, "refund_bp": 300, "source": "antagande"}}
        self.prepare(weak)
        a = assess_initiative(self.config, self.config_dir, self.register, "mallar", "yorgo")
        self.assertFalse(a.ready)
        self.assertTrue(any("pessimistiskt" in r for r in a.result["reasons"]))
        self.assertEqual(a.result["fixed_costs"]["founder_time_per_day_minor"], round(10 * 10_000 / 7))
        with self.assertRaises(AssessmentError):
            self.register.assessments.approve("yorgo", a.assessment_id, "ändå")

    def test_zero_sales_stress_and_scenarios_come_from_the_register(self):
        """Verifies D-058: scenarierna byggs från registret, antaganden märks, och noll försäljning prövas."""
        self.prepare()
        rules = load_assessment_rules(self.config_dir)
        market, fixed, assumptions = scenario_inputs("mallar", STRONG, PLATFORM, rules)
        self.assertEqual((market.fee_fixed, market.fee_bp), (30 * 11, 500))  # USD-cent räknas om
        self.assertTrue(any("växelkurs" in x for x in assumptions))
        self.assertTrue(any("efterfrågan är ett antagande" in x for x in assumptions))
        a = assess_initiative(self.config, self.config_dir, self.register, "mallar", "yorgo")
        zero = a.result["scenarios"]["zero_sales"]
        self.assertTrue(all(r["revenue_minor"] == 0 for r in zero["runs"]))
        sens = [s["parameter"] for s in a.result["sensitivity"] if "parameter" in s]
        self.assertEqual(len(sens), 6)
        spreads = [s["spread"] for s in a.result["sensitivity"] if "spread" in s]
        self.assertEqual(spreads, sorted(spreads, reverse=True))

    def test_only_in_sim(self):
        """Verifies SR-11: bedömningen körs bara med simulerade pengar."""
        self.prepare()
        prod = replace(self.config, system=replace(self.config.system, environment="prod"))
        with self.assertRaises(SimulationError):
            assess_initiative(prod, self.config_dir, self.register, "mallar", "yorgo")


class TestAutoPause(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(TEST_CONFIG)
        self.audit = AuditLog(self.db)
        agents = AgentRegistry(permissions, self.db)
        self.day = "2027-01-01"
        clock = lambda: f"{self.day}T12:00:00+00:00"  # noqa: E731
        self.register = Register(self.db, agents, permissions, self.audit, FOUNDERS, clock=clock)
        auth = AuthorizationEngine(permissions, agents, "sim", self.audit)
        departments = {m.department for m in permissions.roles.values()}
        self.ledger = Ledger(self.db, auth, departments, FOUNDERS, self.audit, 10_000, clock=clock)
        self.incidents = IncidentLog(self.db, agents, permissions, self.audit, FOUNDERS, clock=clock)
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "platform", "plattform-a", status, PLATFORM, "test")
            self.register.record("yorgo", "initiative", "mallar", status, STRONG, "test")
        a = self.register.assessments.record("yorgo", "mallar", "plattform-a", STRONG, PLATFORM,
                                             evidence(1_000), True)
        self.register.assessments.approve("yorgo", a.assessment_id, "test")
        for key, kind in (("plattform-a", "platform"), ("mallar", "initiative")):
            self.register.set_status("yorgo", kind, key, "approved", "test")
        self.register.set_status("yorgo", "initiative", "mallar", "active", "startad")
        self.n = 0

    def sale(self, amount):
        self.n += 1
        self.ledger.record("robin", EntryDraft(f"k{self.n}", "research", amount, "SIM", EntryType.REVENUE, "mallar",
                                               Approval.NOT_REQUIRED, ("file:x",), status=Status.SETTLED))

    def test_below_the_pessimistic_forecast_for_14_days_pauses_with_an_incident(self):
        """Verifies D-058 och FR-15: 14 dagar under den pessimistiska prognosen ger paus och en incident."""
        for d in range(1, 15):
            self.day = f"2027-01-{d:02d}"
            self.sale(500)  # 500 per dag mot prognosen 1 000
        self.assertEqual(check_active(self.register, self.ledger, self.incidents, "2027-01-13", 14), [])  # för tidigt
        paused = check_active(self.register, self.ledger, self.incidents, "2027-01-14", 14)
        self.assertEqual(paused, ["mallar"])
        entry = self.register.get("initiative", "mallar")
        self.assertEqual((entry.status, entry.actor), ("paused", SYSTEM))
        self.assertIn("autopause", [i.source.split(":")[0] for i in self.incidents.all()])
        with self.assertRaises(RegistryError):  # systemet startar aldrig om; det gör en grundare
            self.register.set_status(SYSTEM, "initiative", "mallar", "active", "igen")

    def test_on_or_above_the_forecast_it_stays_active(self):
        """Verifies D-058: på eller över den pessimistiska prognosen fortsätter initiativet."""
        for d in range(1, 15):
            self.day = f"2027-01-{d:02d}"
            self.sale(1_000)
        self.assertEqual(check_active(self.register, self.ledger, self.incidents, "2027-01-14", 14), [])
        self.assertEqual(self.register.get("initiative", "mallar").status, "active")


if __name__ == "__main__":
    unittest.main()
