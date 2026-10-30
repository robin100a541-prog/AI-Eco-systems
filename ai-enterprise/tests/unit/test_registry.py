"""Tester för plattforms- och initiativregistret (PR 4, D-056). Verifierar D-056, D-054, D-011, §30 och FR-25."""
import contextlib
import io
import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import load_permissions
from aie.collaboration import OpportunityRegister
from aie.config import Money
from aie.memory import Database
from aie.monitoring import shutdown_logging
from aie.registry import SYSTEM, AssessmentError, Register, RegistryError, import_dir
from aie.registry.cli import registry as registry_cli

from .fixture_config import TEST_CONFIG

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
FEES = {k: None for k in ("per_order_minor", "percent_bp", "per_listing_minor", "monthly_minor", "setup_minor",
                          "payout_minor")} | {"currency": "USD", "notes": "test"}
PLATFORM = {"name": "Plattform A", "url": "https://example.com", "type": "product", "fees": FEES, "currency": "USD",
            "payment_terms": "okänt", "vat_responsibility": "okänt", "dac7": "okänt", "ai_rules": "okänt",
            "automation_rules": "okänt", "account_requirements": "okänt", "payout_terms": "okänt",
            "dependencies": [], "risks": [], "sources": [{"url": "https://example.com/villkor", "read_on": "2026-10-28"}]}
INITIATIVE = {"platform": "plattform-a", "department": "research", "offering": "product", "description": "mallar",
              "price_minor": 4_900, "unit_cost_minor": 0, "currency": "SIM", "founder_hours_per_week": 2,
              "demand": {"visitors_per_day": 40, "conversion_bp": 300, "refund_bp": 200, "source": "antagande"}}
ORG = (("ceo-1", "ceo", None), ("cfo-1", "cfo", None), ("comp-1", "compliance", None),
       ("lead-1", "research_lead", "ceo-1"), ("res-1", "researcher", "lead-1"))


class RegisterCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(TEST_CONFIG)
        audit = AuditLog(self.db)
        self.agents = AgentRegistry(permissions, self.db)
        for agent_id, role, manager in ORG:
            self.agents.register(agent_id, role, manager, "yorgo", "test")
            for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                self.agents.transition(agent_id, state, "yorgo", "test")
        self.opps = OpportunityRegister(self.db, self.agents, permissions, audit, FOUNDERS)
        self.register = Register(self.db, self.agents, permissions, audit, FOUNDERS, self.opps)

    def assessed(self, initiative="mallar", platform="plattform-a", data=None, ready=True):
        """En godkänd bedömning med exakt de parametrar som initiativet och plattformen har (D-058)."""
        a = self.register.assessments.record("yorgo", initiative, platform, data or INITIATIVE,
                                             self.register.get("platform", platform).data, {"test": True}, ready)
        return self.register.assessments.approve("yorgo", a.assessment_id, "ok") if ready else a

    def approved_pair(self, initiative="mallar", platform="plattform-a"):
        """Plattform och initiativ granskade, en godkänd bedömning, och därefter båda godkända."""
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "platform", platform, status, PLATFORM, "test")
            self.register.record("yorgo", "initiative", initiative, status, INITIATIVE, "test")
        self.assessed(initiative, platform)
        self.register.set_status("yorgo", "platform", platform, "approved", "test")
        self.register.set_status("yorgo", "initiative", initiative, "approved", "test")


class TestSeedData(RegisterCase):
    def test_the_three_platforms_from_channels_md_are_imported_as_data(self):
        """Verifies D-056: plattformarna kommer från config/registry/, med okända belopp som None, och importen kan upprepas."""
        lines = import_dir(self.register, "yorgo", ROOT / "config")
        self.assertEqual(len(lines), 3)
        platforms = {e.key: e for e in self.register.all("platform")}
        self.assertEqual(set(platforms), {"etsy", "gumroad", "fiverr"})
        self.assertTrue(all(e.status == "investigated" for e in platforms.values()))
        self.assertEqual((platforms["etsy"].data["fees"]["percent_bp"], platforms["etsy"].data["fees"]["per_order_minor"]),
                         (650, None))
        self.assertTrue(all(e.data["sources"] for e in platforms.values()))
        self.assertTrue(all("oförändrad" in line for line in import_dir(self.register, "yorgo", ROOT / "config")))

    def test_no_platform_name_is_hard_coded_in_src(self):
        """Verifies D-056: inget plattformsnamn står i src/; nya plattformar läggs till som data."""
        hits = [str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*.py")
                if re.search(r"etsy|gumroad|fiverr", p.read_text(encoding="utf-8"), re.IGNORECASE)]
        self.assertEqual(hits, [])


class TestVersions(RegisterCase):
    def test_every_change_is_a_new_version_and_nothing_is_rewritten(self):
        """Verifies D-056 och §30: varje ändring blir en ny version; historiken går inte att ändra eller radera."""
        self.register.record("yorgo", "platform", "plattform-a", "investigated", PLATFORM, "första")
        changed = PLATFORM | {"payout_terms": "30 dagar"}
        entry = self.register.record("yorgo", "platform", "plattform-a", "investigated", changed, "villkor lästa")
        self.assertEqual((entry.version, entry.data["payout_terms"]), (2, "30 dagar"))
        self.assertEqual([e.data["payout_terms"] for e in self.register.history("platform", "plattform-a")],
                         ["okänt", "30 dagar"])
        for sql in ("UPDATE registry_versions SET status = 'approved'", "DELETE FROM registry_versions"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)

    def test_invalid_data_and_transitions_are_refused(self):
        """Verifies D-056 och D-006: saknade fält, flyttal, källa utan datum och otillåtna statusbyten avvisas."""
        for data in ({k: v for k, v in PLATFORM.items() if k != "fees"},
                     PLATFORM | {"sources": [{"url": "https://example.com"}]},
                     PLATFORM | {"fees": FEES | {"percent_bp": 6.5}},
                     PLATFORM | {"type": "app"}):
            with self.subTest(), self.assertRaises(RegistryError):
                self.register.record("yorgo", "platform", "plattform-b", "investigated", data, "test")
        with self.assertRaises(RegistryError):
            self.register.record("yorgo", "platform", "plattform-b", "approved", PLATFORM, "hoppar över steg")
        self.register.record("yorgo", "platform", "plattform-a", "investigated", PLATFORM, "test")
        for item in (INITIATIVE | {"price_minor": 49.0}, INITIATIVE | {"demand": {"visitors_per_day": 1}}):
            with self.subTest(), self.assertRaises(RegistryError):
                self.register.record("yorgo", "initiative", "mallar", "investigated", item, "test")


class TestWhoDecides(RegisterCase):
    def test_agents_propose_and_investigate_through_the_opportunity_case(self):
        """Verifies D-011 och FR-25: agenter föreslår och utreder via "Utred möjlighet"; bara grundare godkänner."""
        self.register.record("res-1", "platform", "plattform-a", "idea", PLATFORM, "förslag")
        with self.assertRaises(RegistryError):
            self.register.record("res-1", "platform", "plattform-a", "investigated", PLATFORM, "utan ärende")
        opp = self.opps.open("lead-1", "channel", "Plattform A", "Kan vi sälja mallar där?")
        self.opps.submit_findings("res-1", opp.opportunity_id, "avgifter och villkor", ("url:https://example.com",))
        self.register.record("res-1", "platform", "plattform-a", "investigated", PLATFORM, "utredd",
                             opportunity_id=opp.opportunity_id)
        with self.assertRaises(RegistryError):  # Compliance och CFO har inte granskat än
            self.register.record("comp-1", "platform", "plattform-a", "reviewed", PLATFORM, "granskad",
                                 opportunity_id=opp.opportunity_id)
        self.opps.compliance_review("comp-1", opp.opportunity_id, "ok", "villkoren tillåter AI med märkning")
        self.opps.cfo_estimate("cfo-1", opp.opportunity_id, "netto efter avgifter", Money(1_000, "SIM"))
        self.register.record("comp-1", "platform", "plattform-a", "reviewed", PLATFORM, "granskad",
                             opportunity_id=opp.opportunity_id)
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "initiative", "mallar", status, INITIATIVE, "test")
        self.assessed()
        for actor in ("ceo-1", "cfo-1", SYSTEM):
            with self.subTest(actor=actor), self.assertRaises(RegistryError):
                self.register.set_status(actor, "platform", "plattform-a", "approved", "godkänner")
        self.assertEqual(self.register.set_status("yorgo", "platform", "plattform-a", "approved", "ok").status, "approved")

    def test_an_initiative_needs_an_approved_platform_and_the_system_may_only_pause(self):
        """Verifies D-056: ett initiativ godkänns bara på en godkänd plattform; systemet får bara pausa."""
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "platform", "plattform-a", status, PLATFORM, "test")
            self.register.record("yorgo", "initiative", "mallar", status, INITIATIVE, "test")
        self.assessed()
        with self.assertRaises(RegistryError):
            self.register.set_status("yorgo", "initiative", "mallar", "approved", "plattformen är inte godkänd")
        self.register.set_status("yorgo", "platform", "plattform-a", "approved", "test")
        self.register.set_status("yorgo", "initiative", "mallar", "approved", "test")
        self.register.set_status("yorgo", "initiative", "mallar", "active", "test")
        self.assertEqual(self.register.set_status(SYSTEM, "initiative", "mallar", "paused", "under prognosen").status,
                         "paused")
        with self.assertRaises(RegistryError):
            self.register.set_status(SYSTEM, "initiative", "mallar", "active", "systemet startar inte om")


class TestSpendGate(RegisterCase):
    def test_spend_gate_follows_the_register(self):
        """Verifies D-054 och D-056: okänt, ej godkänt, fel departement eller ej godkänd plattform ger ett skäl."""
        self.assertIn("finns inte", self.register.spend_block_reason("research", "mallar"))
        self.register.record("yorgo", "platform", "plattform-a", "investigated", PLATFORM, "test")
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "initiative", "mallar", status, INITIATIVE, "test")
        self.assertIn("reviewed", self.register.spend_block_reason("research", "mallar"))
        self.register.record("yorgo", "platform", "plattform-a", "reviewed", PLATFORM, "test")
        self.assessed()
        self.register.set_status("yorgo", "platform", "plattform-a", "approved", "test")
        self.register.set_status("yorgo", "initiative", "mallar", "approved", "test")
        self.assertIsNone(self.register.spend_block_reason("research", "mallar"))
        self.assertIn("departementet", self.register.spend_block_reason("finance", "mallar"))
        self.register.set_status("yorgo", "platform", "plattform-a", "paused", "kontot granskas")
        self.assertIn("plattformen", self.register.spend_block_reason("research", "mallar"))


class TestSimulateBeforeStart(RegisterCase):
    def test_no_approval_without_an_approved_ready_assessment(self):
        """Verifies D-058: utan en godkänd och redo bedömning godkänns varken plattform eller initiativ."""
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "platform", "plattform-a", status, PLATFORM, "test")
            self.register.record("yorgo", "initiative", "mallar", status, INITIATIVE, "test")
        with self.assertRaises(RegistryError):
            self.register.set_status("yorgo", "platform", "plattform-a", "approved", "ingen bedömning")
        not_ready = self.assessed(ready=False)
        with self.assertRaises(AssessmentError):  # en bedömning som inte är redo kan inte godkännas
            self.register.assessments.approve("yorgo", not_ready.assessment_id, "ändå")
        with self.assertRaises(RegistryError):
            self.register.set_status("yorgo", "platform", "plattform-a", "approved", "fortfarande ingen")

    def test_changed_parameters_invalidate_the_assessment(self):
        """Verifies D-058: ändras priset eller plattformens avgifter efter godkännandet gäller bedömningen inte."""
        self.approved_pair()
        self.assertIsNone(self.register.spend_block_reason("research", "mallar"))
        cheaper = INITIATIVE | {"price_minor": 2_900}
        with self.assertRaises(RegistryError):  # nya parametrar kan inte godkännas med den gamla bedömningen
            self.register.record("yorgo", "initiative", "mallar", "approved", cheaper, "sänkt pris")
        self.register.record("yorgo", "initiative", "mallar", "reviewed", cheaper, "sänkt pris, bedöms om")
        self.assertIn("reviewed", self.register.spend_block_reason("research", "mallar"))
        with self.assertRaises(RegistryError):
            self.register.set_status("yorgo", "initiative", "mallar", "approved", "utan ny bedömning")
        self.assessed(data=cheaper)
        self.register.set_status("yorgo", "initiative", "mallar", "approved", "ny bedömning godkänd")
        self.assertIsNone(self.register.spend_block_reason("research", "mallar"))
        new_fees = PLATFORM | {"fees": FEES | {"percent_bp": 1_500}}
        with self.assertRaises(RegistryError):  # nya avgifter: ingen bedömning med de parametrarna
            self.register.record("yorgo", "platform", "plattform-a", "approved", new_fees, "nya avgifter")

    def test_scenario_assessments_only_exist_in_simulation_databases(self):
        """Verifies D-058: en scenariobedömning kan aldrig skapas utanför simuleringen."""
        self.register.record("yorgo", "platform", "plattform-a", "investigated", PLATFORM, "test")
        with self.assertRaises(AssessmentError):
            self.register.assessments.record("yorgo", "mallar", "plattform-a", INITIATIVE, PLATFORM, {}, True,
                                             kind="scenario")


class TestCommand(unittest.TestCase):
    def test_import_list_and_show(self):
        """Verifies D-056: python -m aie registry import, list och show."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        config = Path(tmp.name) / "config"
        shutil.copytree(TEST_CONFIG, config)
        text = (config / "system.toml").read_text(encoding="utf-8")
        text = text.replace('data_dir = "data"', f'data_dir = "{(Path(tmp.name) / "data").as_posix()}"')
        text = text.replace('log_dir = "logs"', f'log_dir = "{(Path(tmp.name) / "logs").as_posix()}"')
        (config / "system.toml").write_text(text, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(registry_cli(config, "import", founder="yorgo"), 0)
            self.assertEqual(registry_cli(config, "list"), 0)
            self.assertEqual(registry_cli(config, "show", "platform", "gumroad"), 0)
        shutdown_logging()
        self.assertIn("platform   fiverr", out.getvalue())
        self.assertIn('"percent_bp": 1000', out.getvalue())


if __name__ == "__main__":
    unittest.main()
