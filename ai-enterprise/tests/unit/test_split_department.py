"""Tester för uppdelade köp per departement och dag och för initiativspärren (F6, D-054). Verifierar D-054,
ER-04, ER-03, §5 och §21."""
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, Risk, SpendApprovals, SpendRequest, load_budgets
from aie.config import load_config
from aie.config.models import Money
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database

from .fixture_config import TEST_CONFIG

FOUNDERS = frozenset({"robin", "yorgo"})
NOW = datetime(2027, 3, 1, 12, tzinfo=UTC)


class Registry:
    """Ett minimalt initiativregister med samma gränssnitt som PR 4:s register."""

    def __init__(self, approved=(), known=()):
        self.approved, self.known = set(approved), set(known) | set(approved)

    def spend_block_reason(self, department, initiative):
        if initiative not in self.known:
            return f"initiativet {initiative!r} finns inte i initiativregistret (D-054)"
        if initiative not in self.approved:
            return f"initiativet {initiative!r} är inte godkänt (D-054)"
        return None


class SplitCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(TEST_CONFIG)
        departments = {m.department for m in permissions.roles.values()}
        self.limits = replace(load_config(TEST_CONFIG).risk, human_approval_threshold=Money(1_000, "SIM"))
        self.audit = AuditLog(self.db)
        auth = AuthorizationEngine(permissions, AgentRegistry(permissions, self.db), "sim", self.audit)
        clock = lambda: NOW.isoformat(timespec="seconds")  # noqa: E731
        self.ledger = Ledger(self.db, auth, departments, FOUNDERS, self.audit, 1_000, clock=clock)
        self.budgets = load_budgets(TEST_CONFIG, departments, self.limits)
        self.approvals = SpendApprovals(self.db, self.audit, FOUNDERS, clock=clock)
        self.ledger.record("robin", EntryDraft("start", "finance", 1_000_000, "SIM", EntryType.CAPITAL_IN, "start",
                                               Approval.APPROVED, ("decision:start",), status=Status.SETTLED))
        self.n = 0

    def engine(self, registry=None):
        return BudgetEngine(self.ledger, self.limits, self.budgets, self.audit, clock=lambda: NOW,
                            approvals=self.approvals, initiatives=registry)

    def buy(self, amount, initiative, department="research"):
        self.n += 1
        return self.ledger.record("robin", EntryDraft(f"k{self.n}", department, amount, "SIM", EntryType.COST,
                                                      initiative, Approval.NOT_REQUIRED, ("file:kvitto.pdf",),
                                                      status=Status.SETTLED))


class TestDepartmentDay(SplitCase):
    def test_many_small_spends_under_different_names_are_flagged(self):
        """Verifies D-054 och ER-04: små utgifter med olika initiativnamn samma dag flaggas som uppdelning."""
        for n in range(5):
            self.buy(250, f"namn-{n}")  # 1 250 totalt, var och en under tröskeln 1 000
        check = self.engine().check("lead-1", SpendRequest("research", 250, "SIM", "namn-5", Risk.LOW))
        self.assertFalse(check.allowed)
        self.assertTrue(any("i departementet 'research' i dag" in f for f in check.flags))
        self.assertEqual(check.required_approvals, 1)

    def test_other_departments_and_small_totals_are_not_flagged(self):
        """Verifies D-054: under tröskeln, eller i ett annat departement, flaggas inget."""
        self.buy(300, "a")
        self.buy(300, "b", department="finance")
        check = self.engine().check("lead-1", SpendRequest("research", 300, "SIM", "c", Risk.LOW))
        self.assertTrue(check.allowed, check.describe())

    def test_an_approval_does_not_bypass_hard_limits(self):
        """Verifies §21 och D-053: ett godkännande löser uppdelningsflaggan men aldrig en hård gräns."""
        for n in range(5):
            self.buy(250, f"namn-{n}")
        a = self.approvals.request("lead-1", "research", "namn-5", 25_000, "SIM", "test", risk_class=Risk.LOW)
        self.approvals.approve("yorgo", a.approval_id, "ok")
        engine = self.engine()
        check = engine.check("lead-1", SpendRequest("research", 25_000, "SIM", "namn-5", Risk.LOW),
                             approval_id=a.approval_id)
        self.assertFalse(check.allowed)
        self.assertTrue(any("MAX_SINGLE_TRANSACTION" in r for r in check.blocked))
        ok = engine.check("lead-1", SpendRequest("research", 250, "SIM", "namn-5", Risk.LOW), approval_id=a.approval_id)
        self.assertTrue(ok.allowed, ok.describe())


class TestInitiativeGate(SplitCase):
    def test_unknown_and_unapproved_initiatives_are_refused(self):
        """Verifies D-054: utgifter görs bara för initiativ som finns i registret och är godkända."""
        engine = self.engine(Registry(approved={"etsy-mallar"}, known={"utkast"}))
        for name, text in (("okänt", "finns inte"), ("utkast", "inte godkänt")):
            with self.subTest(name=name):
                check = engine.check("lead-1", SpendRequest("research", 100, "SIM", name, Risk.LOW))
                self.assertFalse(check.allowed)
                self.assertTrue(any(text in r for r in check.blocked))
        self.assertTrue(engine.check("lead-1", SpendRequest("research", 100, "SIM", "etsy-mallar", Risk.LOW)).allowed)

    def test_a_failing_registry_means_no(self):
        """Verifies §59: kan registret inte svara blir svaret nej."""
        class Broken:
            def spend_block_reason(self, department, initiative):
                raise RuntimeError("trasig")

        check = self.engine(Broken()).check("lead-1", SpendRequest("research", 100, "SIM", "x", Risk.LOW))
        self.assertFalse(check.allowed)

    def test_without_a_registry_nothing_changes(self):
        """Verifies D-054: innan registret är kopplat (PR 4) görs ingen initiativkontroll."""
        self.assertTrue(self.engine().check("lead-1", SpendRequest("research", 100, "SIM", "vad-som-helst", Risk.LOW)).allowed)


if __name__ == "__main__":
    unittest.main()
