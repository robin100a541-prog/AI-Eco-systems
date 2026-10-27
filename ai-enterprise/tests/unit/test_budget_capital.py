"""Tester för kapitalbaserade budgetar och avgifter som försäljningskostnad (D-047). Verifierar D-047, ER-03,
ER-05, ER-13, ER-19 och §5."""
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, load_budgets
from aie.config import ConfigError, load_config
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.risk import StopLoss
from aie.tax import TaxEngine, load_tax_config

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
CAPITAL = """config_version = 1
mode = "capital"
[departments.research]
share = 40
max_commitment = 20_000
risk_room = "medium"
purpose = "försök"
[departments.finance]
share = 5
max_commitment = 5_000
risk_room = "low"
purpose = "bokföring"
"""


class CapitalCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(ROOT / "config")
        self.departments = {m.department for m in permissions.roles.values()}
        self.limits = load_config(ROOT / "config").risk
        self.audit = AuditLog(self.db)
        auth = AuthorizationEngine(permissions, AgentRegistry(permissions, self.db), "sim", self.audit)
        self.ledger = Ledger(self.db, auth, self.departments, FOUNDERS, self.audit, approval_threshold=10_000)
        self.tax = TaxEngine(self.db, self.ledger, load_tax_config(ROOT / "config", FOUNDERS), self.audit, FOUNDERS)
        self.budgets = self.load(CAPITAL)
        self.engine = BudgetEngine(self.ledger, self.limits, self.budgets, self.audit, tax=self.tax)
        self.n = 0
        self.book("finance", EntryType.CAPITAL_IN, 400_000, Approval.APPROVED, ("decision:start",))  # 100 000 över reserven

    def load(self, text):
        (self.dir / "budgets.toml").write_text(text, encoding="utf-8")
        return load_budgets(self.dir, self.departments, self.limits)

    def book(self, department, kind, amount, approval=Approval.NOT_REQUIRED, evidence=("file:kvitto.pdf",)):
        self.n += 1
        if amount > 10_000 and approval is Approval.NOT_REQUIRED:  # ER-14: över tröskeln krävs godkännande
            approval, evidence = Approval.APPROVED, ("decision:test",)
        return self.ledger.record("robin", EntryDraft(f"k{self.n}", department, amount, "SIM", kind, "etsy",
                                                      approval, evidence, status=Status.SETTLED))

    def ask(self, amount):
        return self.engine.check("robin", SpendRequest("research", amount, "SIM", "etsy", Risk.LOW))


class TestConfig(CapitalCase):
    def test_capital_mode_is_validated(self):
        """Verifies D-047: andelar 1–100 %, summa högst 100 %, inga fasta budgetar i kapitalläget."""
        self.assertEqual((self.budgets["research"].share_percent, self.budgets["research"].budget_minor), (40, None))
        for broken in (CAPITAL.replace("share = 40", "share = 0"),
                       CAPITAL.replace("share = 40", "share = 96"),
                       CAPITAL.replace("share = 40", "budget = 40_000"),
                       CAPITAL.replace('mode = "capital"', 'mode = "monthly"')):
            with self.subTest(), self.assertRaises(ConfigError):
                self.load(broken)

    def test_fixed_mode_is_still_the_default(self):
        """Verifies D-026 och D-047: utan mode gäller fasta budgetar som förut."""
        budgets = load_budgets(ROOT / "config", self.departments, self.limits)
        self.assertFalse(any(b.capital_based for b in budgets.values()))


class TestBudgetFromCapital(CapitalCase):
    def test_budget_is_a_share_of_disposable_capital(self):
        """Verifies D-047 och ER-05: departementet får använda sin andel av det disponibla, aldrig reserven."""
        self.assertEqual(self.engine.usage("research"), (0, 40_000))  # 40 % av 100 000 över reserven
        self.assertTrue(self.ask(9_000).allowed)
        self.assertTrue(any("40 % av disponibelt kapital" in r for r in self.ask(40_001).blocked))

    def test_budget_grows_with_profit_and_shrinks_with_loss(self):
        """Verifies D-047: vinster återinvesteras automatiskt genom att andelen växer; förluster krymper den."""
        self.book("research", EntryType.REVENUE, 50_000)
        grown = self.engine.usage("research")[1]
        # 150 000 över reserven, minus skatt på intäkten utan spår (50 %, högsta satsen) = 125 000; 40 % av det
        self.assertEqual(grown, 50_000)
        self.book("research", EntryType.COST, 50_000)
        self.assertLess(self.engine.usage("research")[1], grown)

    def test_reserved_tax_lowers_the_budget(self):
        """Verifies ER-19 och D-047: reserverad skatt är aldrig disponibel och minskar därför andelen."""
        sale = self.book("research", EntryType.REVENUE, 50_000)
        self.tax.assign("robin", sale.entry_id, "partnership")  # 40 % av 50 000 = 20 000 reserveras
        untaxed = BudgetEngine(self.ledger, self.limits, self.budgets, self.audit)
        self.assertEqual(untaxed.usage("research")[1] - self.engine.usage("research")[1], 20_000 * 40 // 100)


class TestFeesAreCostOfSales(CapitalCase):
    def test_platform_fees_do_not_count_against_the_department(self):
        """Verifies D-047: Etsy- och Gumroad-avgifter dras från intäkterna men belastar inte departementets budget."""
        ok = (Approval.APPROVED, ("decision:test",))
        self.book("research", EntryType.REVENUE, 100_000, *ok)
        self.book("research", EntryType.FEE, 60_000, *ok)
        self.book("research", EntryType.COST, 1_000)
        spent, _ = self.engine.usage("research")
        self.assertEqual(spent, 1_000)
        fixed = BudgetEngine(self.ledger, self.limits, load_budgets(ROOT / "config", self.departments, self.limits),
                             self.audit)
        self.assertEqual(fixed.usage("research")[0], 61_000)  # fast läge: avgifterna räknas som förut

    def test_stoploss_does_not_stop_a_profitable_department_for_its_fees(self):
        """Verifies D-047 och ER-13: i kapitalläget löser avgifter inte ut stop-loss för departementet."""
        for _ in range(20):
            self.book("research", EntryType.REVENUE, 10_000)
            self.book("research", EntryType.FEE, 3_000)
        stoploss = StopLoss(self.db, self.ledger, self.limits, self.budgets, self.audit, FOUNDERS)
        self.assertFalse([b for b in stoploss.breaches() if b.scope_kind == "department"])


if __name__ == "__main__":
    unittest.main()
