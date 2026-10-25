"""Tester för uppdelningsdetekteringen i budgetmotorn (Fas 4d). Verifierar ER-04, §5 och D-028."""

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, load_budgets
from aie.config import load_config
from aie.config.models import Money
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


class SplitCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(ROOT / "config")
        departments = {m.department for m in permissions.roles.values()}
        self.audit = AuditLog(self.db)
        authz = AuthorizationEngine(
            permissions, AgentRegistry(permissions, self.db), "sim", self.audit
        )
        self.recorded_at = NOW
        self.ledger = Ledger(
            self.db,
            authz,
            departments,
            FOUNDERS,
            self.audit,
            approval_threshold=100,
            clock=lambda: self.recorded_at.isoformat(timespec="seconds"),
        )
        base = load_config(ROOT / "config").risk
        # ROADMAP:s exempel: gräns 100. MAX_SINGLE_TRANSACTION sätts högt så att bara tröskeln prövas.
        self.limits = replace(base, human_approval_threshold=Money(100, "SIM"))
        self.budgets = load_budgets(ROOT / "config", departments, base)
        self.engine = BudgetEngine(
            self.ledger, self.limits, self.budgets, self.audit, clock=lambda: NOW
        )
        self.n = 0
        self.ledger.record(
            "robin",
            EntryDraft(
                "start",
                "finance",
                1_000_000,
                "SIM",
                EntryType.CAPITAL_IN,
                "start",
                Approval.APPROVED,
                ("decision:start",),
                status=Status.SETTLED,
            ),
        )

    def buy(
        self,
        amount=99,
        initiative="etsy-mallar",
        approval=Approval.NOT_REQUIRED,
        days_ago=0,
    ):
        self.n += 1
        self.recorded_at = NOW - timedelta(days=days_ago)
        evidence = (
            ("approval:1",) if approval is Approval.APPROVED else ("file:kvitto.pdf",)
        )
        return self.ledger.record(
            "robin",
            EntryDraft(
                f"k{self.n}",
                "research",
                amount,
                "SIM",
                EntryType.COST,
                initiative,
                approval,
                evidence,
                status=Status.SETTLED,
            ),
        )

    def check(self, amount=99, initiative="etsy-mallar"):
        return self.engine.check(
            "cfo-1", SpendRequest("research", amount, "SIM", initiative, Risk.LOW)
        )


class TestSplit(SplitCase):
    def test_ten_purchases_of_99_under_limit_100_are_flagged(self):
        """ROADMAP Fas 4 nyckeltest (ER-04): 10 köp à 99 under gräns 100 i samma initiativ → flaggas."""
        for _ in range(9):
            self.buy()
        check = self.check()  # det tionde köpet
        self.assertFalse(check.allowed)
        self.assertEqual(
            check.blocked, ()
        )  # ingen blockering, men grundarna måste avgöra
        self.assertEqual(check.required_approvals, 2)
        self.assertEqual(len(check.flags), 1)
        self.assertIn(
            "10 utgifter i 'etsy-mallar' på 7 dagar blir tillsammans 990 > HUMAN_APPROVAL_THRESHOLD 100",
            check.flags[0],
        )
        entry = list(self.audit.entries())[-1]
        self.assertEqual(
            (entry.action, len(entry.details["flags"])), ("budget.blocked", 1)
        )

    def test_first_purchase_and_purchases_under_the_limit_together_pass(self):
        """ER-04: ett ensamt köp, eller köp som tillsammans håller sig under gränsen, flaggas inte."""
        self.assertTrue(self.check().allowed)
        self.buy(50)
        self.assertTrue(self.check(50).allowed)  # 100 är inte över 100

    def test_other_initiatives_old_purchases_and_approved_ones_do_not_count(self):
        """D-028: bara samma initiativ, inom sju dagar, och bara köp som inte redan godkänts av grundarna."""
        self.buy(99, initiative="gumroad")
        self.buy(99, days_ago=8)
        self.buy(5_000, approval=Approval.APPROVED)
        self.assertTrue(self.check().allowed, self.check().describe())
        self.buy(99, days_ago=6)
        self.assertFalse(self.check().allowed)

    def test_large_purchase_is_not_called_a_split(self):
        """En utgift som själv är över gränsen kräver godkännande som vanligt, utan uppdelningsflagga."""
        self.buy()
        check = self.check(101)
        self.assertEqual((check.required_approvals, check.flags), (2, ()))

    def test_pending_purchases_count(self):
        """ER-04: ett väntande köp är också ett åtagande och räknas i summan."""
        self.n += 1
        self.ledger.record(
            "robin",
            EntryDraft(
                "p1",
                "research",
                99,
                "SIM",
                EntryType.COST,
                "etsy-mallar",
                Approval.NOT_REQUIRED,
                ("file:offert.pdf",),
            ),
        )
        self.assertTrue(self.check().flags)


if __name__ == "__main__":
    unittest.main()
