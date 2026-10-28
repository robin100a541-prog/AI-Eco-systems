"""Tester för departementens tak i kapitalläget (F1+F2, D-051). Verifierar D-051, D-047, ER-03, ER-05, ER-17 och §5.

Värdena motsvarar repots konfiguration för 500 kr men är låsta här: startkapital 50 000, reserv 10 000,
REINVESTMENT_POLICY 80 %, andelar 40 + 5 + 5 + 2 + 2 + 2 = 56 % (44 % buffert).
"""
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, load_budgets
from aie.config import load_config
from aie.config.models import Money
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status

from .fixture_config import TEST_CONFIG

FOUNDERS = frozenset({"robin", "yorgo"})
BUDGETS = """config_version = 1
mode = "capital"
[departments.research]
share = 40
max_commitment = 50_000
risk_room = "medium"
purpose = "försök"
[departments.executive]
share = 5
max_commitment = 50_000
risk_room = "low"
purpose = "samordning"
[departments.finance]
share = 5
max_commitment = 50_000
risk_room = "low"
purpose = "bokföring"
[departments.risk]
share = 2
max_commitment = 50_000
risk_room = "low"
purpose = "risk"
[departments.compliance]
share = 2
max_commitment = 50_000
risk_room = "low"
purpose = "juridik"
[departments.audit]
share = 2
max_commitment = 50_000
risk_room = "low"
purpose = "granskning"
"""


class CapCase(unittest.TestCase):
    def setUp(self):
        from aie.memory import Database

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(TEST_CONFIG)
        departments = {m.department for m in permissions.roles.values()}
        base = load_config(TEST_CONFIG).risk
        self.limits = replace(base, start_capital=Money(50_000, "SIM"), minimum_reserve=Money(10_000, "SIM"),
                              max_department_budget=Money(1_000_000, "SIM"), max_single_transaction=Money(50_000, "SIM"),
                              max_committed_capital=Money(1_000_000, "SIM"),
                              human_approval_threshold=Money(1_000_000, "SIM"), reinvestment_policy=Decimal(80))
        (self.dir / "budgets.toml").write_text(BUDGETS, encoding="utf-8")
        budgets = load_budgets(self.dir, departments, self.limits)
        self.audit = AuditLog(self.db)
        auth = AuthorizationEngine(permissions, AgentRegistry(permissions, self.db), "sim", self.audit)
        self.ledger = Ledger(self.db, auth, departments, FOUNDERS, self.audit, approval_threshold=1_000_000)
        self.engine = BudgetEngine(self.ledger, self.limits, budgets, self.audit)
        self.n = 0
        self.book("finance", EntryType.CAPITAL_IN, 50_000)  # 500 kr; bas 40 000 över reserven

    def book(self, department, kind, amount, initiative="etsy"):
        self.n += 1
        return self.ledger.record("robin", EntryDraft(f"k{self.n}", department, amount, "SIM", kind, initiative,
                                                      Approval.NOT_REQUIRED, ("file:kvitto.pdf",), status=Status.SETTLED))

    def spend_until_blocked(self, department="research", step=400, initiatives=False):
        total = 0
        for n in range(10_000):
            initiative = f"initiativ-{n}" if initiatives else "etsy"
            check = self.engine.check("robin", SpendRequest(department, step, "SIM", initiative, Risk.LOW))
            if not check.allowed:
                return total, check
            self.book(department, EntryType.COST, step, initiative)
            total += step
        raise AssertionError("taket nåddes aldrig")


class TestCap(CapCase):
    def test_research_never_spends_more_than_its_share_of_the_base(self):
        """Verifies D-051 och ER-03: research kan aldrig spendera mer än 40 % av basen."""
        self.assertEqual(self.engine.capital_base(), 40_000)
        total, check = self.spend_until_blocked()
        self.assertEqual(total, 16_000)  # 40 % av 40 000
        self.assertTrue(any("departementets tak" in r for r in check.blocked), check.blocked)

    def test_repeated_small_spends_cannot_move_the_cap(self):
        """Verifies D-051: upprepade kontroller och utgifter flyttar aldrig taket (felet i 083bb25 gav 95–99 %)."""
        total, _ = self.spend_until_blocked(step=37)  # 432 utgifter; 37 delar inte 16 000 jämnt
        self.assertEqual(total, 16_000 // 37 * 37)
        self.assertEqual(self.engine.capital_base(), 40_000)  # egna utgifter krymper inte basen

    def test_new_initiatives_do_not_bypass_the_cap(self):
        """Verifies D-051: taket gäller departementet, inte initiativet."""
        total, _ = self.spend_until_blocked(step=500, initiatives=True)
        self.assertEqual(total, 16_000)

    def test_the_buffer_of_44_percent_is_protected(self):
        """Verifies D-051 och §5: alla departement tillsammans når högst 56 % av basen; 44 % är buffert."""
        total = sum(self.spend_until_blocked(department=d, step=200)[0]
                    for d in ("research", "executive", "finance", "risk", "compliance", "audit"))
        self.assertEqual(total, 40_000 * 56 // 100)

    def test_only_80_percent_of_profit_is_reinvested(self):
        """Verifies D-051 och D-047: med REINVESTMENT_POLICY 80 % kan resterande 20 % av vinsten aldrig spenderas."""
        self.book("research", EntryType.REVENUE, 10_000)  # vinst 10 000, ingen skattemotor kopplad
        self.assertEqual(self.engine.capital_base(), 40_000 + 8_000)
        self.assertEqual(self.engine.usage("research")[1], (48_000) * 40 // 100)

    def test_a_loss_shrinks_the_base(self):
        """Verifies D-051: en förlust (till exempel avgifter som är större än intäkterna) minskar basen fullt ut."""
        self.book("research", EntryType.REVENUE, 1_000)
        self.book("research", EntryType.FEE, 6_000)  # förlust 5 000
        self.assertEqual(self.engine.capital_base(), 40_000 - 5_000)

    def test_capital_in_and_out_change_the_base(self):
        """Verifies D-051: insatt kapital är genomförda insättningar minus uttag, inte en konstant."""
        self.book("finance", EntryType.CAPITAL_IN, 10_000)
        self.assertEqual(self.engine.capital_base(), 50_000)
        self.book("finance", EntryType.CAPITAL_OUT, 20_000)
        self.assertEqual(self.engine.capital_base(), 30_000)

    def test_reserve_and_hard_limits_still_apply(self):
        """Verifies ER-05 och §5: reserven och MAX_SINGLE_TRANSACTION gäller fortfarande ovanpå taket."""
        self.engine._limits = replace(self.limits, max_single_transaction=Money(1_000, "SIM"))
        check = self.engine.check("robin", SpendRequest("research", 1_001, "SIM", "etsy", Risk.LOW))
        self.assertTrue(any("MAX_SINGLE_TRANSACTION" in r for r in check.blocked))
        self.engine._limits = self.limits
        self.book("finance", EntryType.CAPITAL_OUT, 39_000)  # kvar 11 000, reserv 10 000 ⇒ disponibelt 1 000
        check = self.engine.check("robin", SpendRequest("research", 1_001, "SIM", "etsy", Risk.LOW))
        self.assertFalse(check.allowed)
        self.assertTrue(any("reserv" in r for r in check.blocked))


if __name__ == "__main__":
    unittest.main()
