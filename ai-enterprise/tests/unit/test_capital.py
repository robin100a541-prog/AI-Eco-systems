"""Tester för src/aie/budget/capital.py och reservskyddet (Fas 4c). Verifierar §5, §23, ER-02, ER-05, ER-10, ER-11 och §52.

Repots gränser: START_CAPITAL 1 000 000 och MINIMUM_RESERVE 300 000 (SIM).
"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, capital_position, load_budgets
from aie.config import load_config
from aie.config.models import Money
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from .fixture_config import TEST_CONFIG

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
T = EntryType


class CapitalCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(TEST_CONFIG)
        self.registry = AgentRegistry(permissions, self.db)
        self.departments = {m.department for m in permissions.roles.values()}
        self.limits = load_config(TEST_CONFIG).risk
        self.audit = AuditLog(self.db)
        self.authz = AuthorizationEngine(permissions, self.registry, "sim", self.audit)
        self.ledger = Ledger(
            self.db,
            self.authz,
            self.departments,
            FOUNDERS,
            self.audit,
            approval_threshold=10_000,
        )
        self.budgets = load_budgets(TEST_CONFIG, self.departments, self.limits)
        self.n = 0

    def book(self, amount, kind, status=Status.SETTLED, department="research"):
        self.n += 1
        approval = (
            Approval.APPROVED
            if kind in (T.CAPITAL_IN, T.CAPITAL_OUT)
            else Approval.NOT_REQUIRED
        )
        if (
            approval is Approval.NOT_REQUIRED
            and amount > 10_000
            and kind is not T.REVENUE
        ):
            approval = Approval.UNAPPROVED
        return self.ledger.record(
            "robin",
            EntryDraft(
                f"k{self.n}",
                department,
                amount,
                "SIM",
                kind,
                "etsy-mallar",
                approval,
                ("decision:1",)
                if approval is Approval.APPROVED
                else ("file:underlag.pdf",),
                status=status,
            ),
        )

    def position(self, limits=None):
        return capital_position(self.ledger.entries(), limits or self.limits)


class TestConcepts(CapitalCase):
    def test_all_seven_concepts_from_the_ledger(self):
        """Verifies §23, ER-10: totalt, likvida, bundet, reserv, åtaget, disponibelt och återinvesterbart hålls isär."""
        self.book(1_000_000, T.CAPITAL_IN)
        self.book(20_000, T.REVENUE)
        self.book(5_000, T.COST)
        self.book(1_000, T.FEE)
        self.book(8_000, T.COST, status=Status.PENDING)
        self.book(
            50_000, T.REVENUE, status=Status.PENDING
        )  # väntad inbetalning (ER-11)
        p = self.position()
        self.assertEqual(
            (
                p.liquid_minor,
                p.bound_minor,
                p.total_minor,
                p.reserve_minor,
                p.committed_minor,
                p.disposable_minor,
                p.reinvestable_minor,
            ),
            (1_014_000, 0, 1_014_000, 300_000, 8_000, 706_000, 0),
        )
        self.assertIn("disponibelt 706000", p.describe())

    def test_expected_income_is_never_liquid(self):
        """Verifies ER-11: en prognos eller väntad betalning ökar aldrig likvida eller disponibla medel."""
        self.book(400_000, T.CAPITAL_IN)
        self.book(500_000, T.REVENUE, status=Status.PENDING)
        self.assertEqual(
            (self.position().liquid_minor, self.position().disposable_minor),
            (400_000, 100_000),
        )

    def test_failed_and_cancelled_do_not_count_but_corrections_do(self):
        """§23: misslyckade poster räknas inte; en korrigering ändrar de likvida medlen med sitt tecken."""
        self.book(500_000, T.CAPITAL_IN)
        failed = self.book(9_000, T.COST, status=Status.PENDING)
        self.ledger.set_status("robin", failed.entry_id, Status.FAILED, "nekades")
        cost = self.book(10_000, T.COST)
        self.ledger.correct(
            "robin", cost.entry_id, -4_000, "fel belopp", ("file:kvitto.pdf",), "fix"
        )
        p = self.position()
        self.assertEqual((p.liquid_minor, p.committed_minor), (494_000, 0))

    def test_withdrawal_reduces_liquid_and_reserve_never_goes_negative(self):
        """§23: uttag minskar likvida medel; disponibelt blir aldrig negativt även om reserven redan är angripen."""
        self.book(350_000, T.CAPITAL_IN)
        self.book(100_000, T.CAPITAL_OUT)
        p = self.position()
        self.assertEqual((p.liquid_minor, p.disposable_minor), (250_000, 0))

    def test_missing_reserve_means_nothing_is_disposable(self):
        """Verifies ER-02: utan MINIMUM_RESERVE kan inget disponeras."""
        self.book(1_000_000, T.CAPITAL_IN)
        p = self.position(replace(self.limits, minimum_reserve=None))
        self.assertEqual((p.reserve_minor, p.disposable_minor), (None, 0))

    def test_reinvestable_is_zero_until_tax_can_be_reserved(self):
        """Verifies ER-19 (försiktigt): vinst före skatt är inte återinvesterbar förrän Tax Engine finns."""
        self.book(1_000_000, T.CAPITAL_IN)
        self.book(100_000, T.REVENUE)
        self.book(10_000, T.COST)
        self.assertEqual(self.position().reinvestable_minor, 0)


class TestReserveIsRespected(CapitalCase):
    def engine(self, limits=None):
        return BudgetEngine(
            self.ledger, limits or self.limits, self.budgets, self.audit
        )

    def spend(self, amount, **kw):
        return replace(
            SpendRequest("research", amount, "SIM", "etsy-mallar", Risk.LOW), **kw
        )

    def test_spending_that_would_touch_the_reserve_is_blocked(self):
        """§52 kriterium "skyddad reserv respekteras" (§5, ER-05): en utgift får aldrig ta av reserven."""
        self.book(310_000, T.CAPITAL_IN)
        self.book(
            5_000, T.COST, status=Status.PENDING
        )  # 310 000 − 300 000 − 5 000 = 5 000 kvar
        self.assertTrue(self.engine().check("cfo-1", self.spend(5_000)).allowed)
        blocked = self.engine().check("cfo-1", self.spend(5_001))
        self.assertFalse(blocked.allowed)
        self.assertTrue(
            any("skyddade reserven" in b and "ER-05" in b for b in blocked.blocked),
            blocked.blocked,
        )

    def test_founder_approval_does_not_unlock_the_reserve(self):
        """§5, ER-05: reserven används inte i normal verksamhet; ett godkännande ändrar inte blockeringen."""
        self.book(300_000, T.CAPITAL_IN)
        check = self.engine().check("robin", self.spend(1))
        self.assertFalse(check.allowed)
        self.assertEqual(
            check.required_approvals, 0
        )  # det är en blockering, inte en fråga om godkännande
        self.assertTrue(check.blocked)

    def test_missing_reserve_blocks_all_spending(self):
        """ER-02: utan MINIMUM_RESERVE blockeras varje utgift."""
        self.book(1_000_000, T.CAPITAL_IN)
        check = self.engine(replace(self.limits, minimum_reserve=None)).check(
            "cfo-1", self.spend(1)
        )
        self.assertIn(
            "MINIMUM_RESERVE saknas; den skyddade reserven kan inte skyddas (ER-02, ER-05)",
            check.blocked,
        )

    def test_reserve_comes_from_config_and_agents_cannot_change_it(self):
        """§5, SR-04: reservens storlek står i risk_limits.toml; inget mandat ger en agent rätt att ändra den."""
        self.assertEqual(self.limits.minimum_reserve, Money(300_000, "SIM"))
        self.registry.register("cfo-1", "cfo", None, "yorgo", "test")
        for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
            self.registry.transition("cfo-1", state, "yorgo", "test")
        with self.assertRaises(PermissionDenied):
            self.authz.require("cfo-1", "governance.change_limits")


if __name__ == "__main__":
    unittest.main()
