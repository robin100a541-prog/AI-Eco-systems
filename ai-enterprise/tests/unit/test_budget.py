"""Tester för src/aie/budget (Fas 4b). Verifierar ER-02, ER-03, ER-14, ER-17, ER-22, §23, §24 och §52.

Repots gränser: MAX_SINGLE_TRANSACTION 20 000, HUMAN_APPROVAL_THRESHOLD 10 000,
MAX_COMMITTED_CAPITAL 400 000. Research har budget 50 000, max_commitment 20 000, riskutrymme medium.
"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import (
    API_SPEND,
    BudgetBlocked,
    BudgetEngine,
    Risk,
    SpendRequest,
    load_budgets,
)
from aie.config import ConfigError, load_config
from aie.config.models import Money
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})


def spend(amount=5_000, **kw):
    return replace(
        SpendRequest("research", amount, "SIM", "etsy-mallar", Risk.LOW), **kw
    )


class BudgetCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.permissions = load_permissions(ROOT / "config")
        self.departments = {m.department for m in self.permissions.roles.values()}
        self.limits = load_config(ROOT / "config").risk
        self.audit = AuditLog(self.db)
        engine = AuthorizationEngine(
            self.permissions,
            AgentRegistry(self.permissions, self.db),
            "sim",
            self.audit,
        )
        self.ledger = Ledger(
            self.db,
            engine,
            self.departments,
            FOUNDERS,
            self.audit,
            approval_threshold=10_000,
        )
        self.budgets = load_budgets(ROOT / "config", self.departments, self.limits)
        self.engine = BudgetEngine(self.ledger, self.limits, self.budgets, self.audit)
        self.n = 0
        # Startkapitalet sätts in som en riktig ledgerpost (§23: kapital räknas bara från ledgern).
        self.ledger.record("robin", EntryDraft(
            "startkapital", "finance", self.limits.start_capital.amount_minor, "SIM", EntryType.CAPITAL_IN,
            "start", Approval.APPROVED, ("decision:start",), status=Status.SETTLED,
        ))

    def book(
        self, amount, kind=EntryType.COST, status=Status.SETTLED, department="research", initiative=None
    ):
        """Bokför en post. Varje post får ett eget initiativ, så att budgettesterna inte ser ut som
        uppdelade köp (ER-04 testas i test_split.py)."""
        self.n += 1
        approval = (
            Approval.UNAPPROVED
            if amount > 10_000 and kind is not EntryType.REVENUE
            else Approval.NOT_REQUIRED
        )
        return self.ledger.record(
            "robin",
            EntryDraft(
                f"k{self.n}",
                department,
                amount,
                "SIM",
                kind,
                initiative or f"initiativ-{self.n}",
                approval,
                ("file:kvitto.pdf",),
                status=status,
            ),
        )

    def actions(self):
        return [e.action for e in self.audit.entries()]


class TestBudget(BudgetCase):
    def test_budget_overrun_is_blocked(self):
        """ROADMAP Fas 4 nyckeltest, §52: budgetöverskridanden blockeras."""
        for _ in range(9):
            self.book(5_000)  # 45 000 av 50 000
        ok = self.engine.check("cfo-1", spend(5_000))
        self.assertTrue(ok.allowed, ok.describe())
        over = self.engine.check("cfo-1", spend(5_001))
        self.assertFalse(over.allowed)
        self.assertIn(
            "budgeten överskrids: 45000 + 5001 > 50000 SIM (§52)", over.blocked
        )
        with self.assertRaises(BudgetBlocked):
            self.engine.require("cfo-1", spend(5_001))
        self.assertIn("budget.blocked", self.actions())
        self.assertIn("budget.allowed", self.actions())

    def test_pending_spend_counts_and_commitments_are_capped(self):
        """§23, ER-17: väntade utgifter räknas mot budgeten och mot departementets max_commitment."""
        self.book(9_000, status=Status.PENDING)
        self.book(9_000, status=Status.PENDING)
        check = self.engine.check("cfo-1", spend(3_000))
        self.assertEqual((check.spent_minor, check.committed_minor), (18_000, 18_000))
        self.assertIn(
            "departementets åtaganden överskrids: 18000 + 3000 > 20000", check.blocked
        )
        self.assertTrue(self.engine.check("cfo-1", spend(2_000)).allowed)

    def test_only_costs_and_fees_use_the_budget(self):
        """Intäkter, återbetalningar, kapital och misslyckade poster ändrar inte budgeten; korrigeringar gör det."""
        self.book(40_000, kind=EntryType.REVENUE)
        self.book(1_000, kind=EntryType.REFUND)
        self.book(1_000, kind=EntryType.CAPITAL_OUT)
        failed = self.book(5_000, status=Status.PENDING)
        self.ledger.set_status("robin", failed.entry_id, Status.FAILED, "nekades")
        cost = self.book(10_000)
        self.book(500, kind=EntryType.FEE)
        self.book(9_000, department="executive")
        self.ledger.correct(
            "robin", cost.entry_id, -4_000, "fel belopp", ("file:kvitto.pdf",), "fix"
        )
        self.assertEqual(self.engine.check("cfo-1", spend()).spent_minor, 6_500)

    def test_single_transaction_limit_and_approval(self):
        """§25, ER-14, D-019: över MAX_SINGLE_TRANSACTION blockeras; över tröskeln krävs båda grundarna."""
        over = self.engine.check("cfo-1", spend(20_001))
        self.assertIn("över MAX_SINGLE_TRANSACTION (20001 > 20000)", over.blocked)
        needs = self.engine.check("cfo-1", spend(10_001))
        self.assertEqual(
            (needs.allowed, needs.blocked, needs.required_approvals), (False, (), 2)
        )
        self.assertIn("kräver 2 grundare", needs.describe())
        self.assertEqual(
            self.engine.check("cfo-1", spend(10_000)).required_approvals, 0
        )

    def test_risk_room_and_critical(self):
        """§24, ER-17: riskklass över departementets utrymme, eller critical, blockeras."""
        self.assertTrue(
            self.engine.check("cfo-1", spend(risk_class=Risk.MEDIUM)).allowed
        )
        self.assertIn(
            "riskklass high är över departementets riskutrymme medium",
            self.engine.check("cfo-1", spend(risk_class=Risk.HIGH)).blocked,
        )
        self.assertIn(
            "riskklass critical tillåts aldrig (§24)",
            self.engine.check("cfo-1", spend(risk_class=Risk.CRITICAL)).blocked,
        )
        self.assertFalse(
            self.engine.check(
                "cfo-1", spend(department="finance", risk_class=Risk.MEDIUM)
            ).allowed
        )

    def test_api_spend_is_locked(self):
        """ER-22, D-009: API_SPEND är 0 tills realiserad nettovinst efter skatt kan visas (Tax Engine, 4f)."""
        self.book(30_000, kind=EntryType.REVENUE)
        check = self.engine.check("cfo-1", spend(1, category=API_SPEND))
        self.assertFalse(check.allowed)
        self.assertIn("API_SPEND", check.blocked[0])

    def test_bad_requests_are_blocked(self):
        """ER-01, ER-15, ER-02: fel belopp, fel valuta, okänt departement eller saknat initiativ blockeras."""
        for request in (
            spend(0),
            spend(-1),
            spend(99.5),
            spend(True),
            spend(currency="SEK"),
            spend(initiative=""),
            spend(department="marknad"),
            spend(risk_class="low"),
        ):
            with self.subTest(request=request):
                self.assertFalse(self.engine.check("cfo-1", request).allowed)

    def test_missing_limits_block(self):
        """ER-02: en saknad gräns betyder blockera, aldrig obegränsat."""
        for name in ("max_single_transaction", "max_committed_capital"):
            engine = BudgetEngine(
                self.ledger,
                replace(self.limits, **{name: None}),
                self.budgets,
                self.audit,
            )
            with self.subTest(name=name):
                self.assertIn(
                    f"{name.upper()} saknas (ER-02)",
                    engine.check("cfo-1", spend()).blocked,
                )
        engine = BudgetEngine(
            self.ledger,
            replace(self.limits, human_approval_threshold=None),
            self.budgets,
            self.audit,
        )
        self.assertEqual(engine.check("cfo-1", spend(1)).required_approvals, 2)
        engine = BudgetEngine(self.ledger, self.limits, {}, self.audit)
        self.assertIn("ingen budget", engine.check("cfo-1", spend()).blocked[0])

    def test_company_wide_commitment_cap(self):
        """§23: summan av alla departements väntade utgifter får inte passera MAX_COMMITTED_CAPITAL."""
        limits = replace(self.limits, max_committed_capital=Money(15_000, "SIM"))
        engine = BudgetEngine(self.ledger, limits, self.budgets, self.audit)
        self.book(9_000, status=Status.PENDING, department="executive")
        self.book(5_000, status=Status.PENDING)
        self.assertIn(
            "företagets åtaganden överskrids: 14000 + 2000 > 15000 (§23)",
            engine.check("cfo-1", spend(2_000)).blocked,
        )


class TestBudgetConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.limits = load_config(ROOT / "config").risk
        self.departments = {"research", "finance"}

    def load(self, body):
        (self.dir / "budgets.toml").write_text(
            "config_version = 1\n" + body, encoding="utf-8"
        )
        return load_budgets(self.dir, self.departments, self.limits)

    def test_repo_budgets_are_valid_and_cover_every_department(self):
        """ER-17: varje departement i permissions.toml har budget, maxåtagande, riskutrymme och användningsområde."""
        permissions = load_permissions(ROOT / "config")
        departments = {m.department for m in permissions.roles.values()}
        budgets = load_budgets(ROOT / "config", departments, self.limits)
        self.assertEqual(set(budgets), departments)
        for b in budgets.values():
            self.assertLessEqual(
                b.budget_minor, self.limits.max_department_budget.amount_minor
            )
            self.assertTrue(b.purpose)

    def test_invalid_budgets_are_refused(self):
        """ER-02, ER-17, §5: fel i filen samlas; inga budgetar över gränsen eller in i reserven."""
        good = (
            'budget = 1_000\nmax_commitment = 500\nrisk_room = "low"\npurpose = "x"\n'
        )
        cases = {
            "okänt departement": "[departments.marknad]\n" + good,
            "MAX_DEPARTMENT_BUDGET": '[departments.research]\nbudget = 200_001\nmax_commitment = 1\nrisk_room = "low"\npurpose = "x"\n',
            "max_commitment får inte": '[departments.research]\nbudget = 100\nmax_commitment = 101\nrisk_room = "low"\npurpose = "x"\n',
            "risk_room": '[departments.research]\nbudget = 100\nmax_commitment = 1\nrisk_room = "critical"\npurpose = "x"\n',
            "purpose saknas": '[departments.research]\nbudget = 100\nmax_commitment = 1\nrisk_room = "low"\n',
            "positivt heltal": '[departments.research]\nbudget = 1.5\nmax_commitment = 1\nrisk_room = "low"\npurpose = "x"\n',
            "okänd nyckel": "[departments.research]\n" + good + "extra = 1\n",
        }
        for expected, body in cases.items():
            with (
                self.subTest(expected=expected),
                self.assertRaisesRegex(ConfigError, expected),
            ):
                self.load(body)

    def test_budgets_cannot_eat_the_reserve(self):
        """§5, ER-05: summan av budgetarna ≤ START_CAPITAL − MINIMUM_RESERVE."""
        limits = replace(
            self.limits,
            start_capital=Money(1_500, "SIM"),
            minimum_reserve=Money(1_000, "SIM"),
        )
        (self.dir / "budgets.toml").write_text(
            'config_version = 1\n[departments.research]\nbudget = 600\nmax_commitment = 1\nrisk_room = "low"\npurpose = "x"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ConfigError, "skyddade reserven"):
            load_budgets(self.dir, self.departments, limits)

    def test_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "saknas"):
            load_budgets(self.dir, self.departments, self.limits)


if __name__ == "__main__":
    unittest.main()
