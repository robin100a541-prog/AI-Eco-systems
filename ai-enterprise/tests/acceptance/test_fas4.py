"""Acceptanstester för Fas 4 (konstitutionen §52, ROADMAP Fas 4).

Hela den ekonomiska kedjan med de riktiga konfigurationsfilerna och en riktig databas: register →
Authorization Engine → ledger → Tax Engine → budgetmotor med spärrar (stop-loss, nödstopp, skyddat
driftläge) → resultat och Audits omräkning.

§52 acceptanskriterier:
1. Budgetöverskridanden blockeras.                     → TestBudgetOverrun
2. Dubbelregistrering hanteras.                        → TestDoubleRegistration
3. Nettovinst kan beräknas från registrerade poster.   → TestNetProfit
4. Skyddad reserv respekteras (även reserverad skatt). → TestReserve
5. Ekonomiska rapporter kan granskas mot underlaget.   → TestAuditable
ROADMAP:s nyckeltester: uppdelade köp flaggas (TestSplit), nödstopp stoppar nya transaktioner utan att
något raderas (TestKillSwitch).
"""
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, load_budgets
from aie.config import load_config
from aie.config.models import Money
from aie.ledger import (
    Approval,
    DuplicateEntry,
    EntryDraft,
    EntryType,
    Ledger,
    Status,
    recompute,
    result_for,
)
from aie.memory import Database
from aie.risk import KillSwitch, ProtectedMode, StopLoss
from aie.tax import TaxEngine, load_tax_config

from .fixture_config import TEST_CONFIG

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
ORG = (("ceo-1", "ceo", None), ("cfo-1", "cfo", None), ("cro-1", "cro", None), ("comp-1", "compliance", None),
       ("audit-1", "auditor", None), ("lead-1", "research_lead", "ceo-1"), ("res-1", "researcher", "lead-1"))


class Fas4Case(unittest.TestCase):
    threshold = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        config = load_config(TEST_CONFIG)
        permissions = load_permissions(TEST_CONFIG)
        departments = {m.department for m in permissions.roles.values()}
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(permissions, self.db)
        for agent_id, role, manager in ORG:
            self.registry.register(agent_id, role, manager, "yorgo", "test")
            for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                self.registry.transition(agent_id, state, "yorgo", "test")
        self.limits = config.risk
        if self.threshold is not None:
            self.limits = replace(self.limits, human_approval_threshold=Money(self.threshold, "SIM"))
        self.kill = KillSwitch(self.db, self.registry, permissions, self.audit, FOUNDERS)
        self.auth = AuthorizationEngine(permissions, self.registry, "sim", self.audit, gates=(self.kill,))
        clock = lambda: NOW.isoformat(timespec="seconds")  # noqa: E731
        self.ledger = Ledger(self.db, self.auth, departments, FOUNDERS, self.audit,
                             self.limits.human_approval_threshold.amount_minor, clock=clock)
        self.tax = TaxEngine(self.db, self.ledger, load_tax_config(TEST_CONFIG, FOUNDERS), self.audit, FOUNDERS,
                             self.auth, clock=clock)
        budgets = load_budgets(TEST_CONFIG, departments, config.risk)
        stoploss = StopLoss(self.db, self.ledger, self.limits, budgets, self.audit, FOUNDERS)
        mode = ProtectedMode(self.db, self.ledger, self.registry, permissions, self.limits, self.auth, self.audit,
                             FOUNDERS, kill_switch=self.kill)
        self.auth.add_gate(mode)
        self.budget = BudgetEngine(self.ledger, self.limits, budgets, self.audit, clock=lambda: NOW,
                                   gates=(stoploss, self.kill, mode), tax=self.tax)
        self.n = 0
        self.book("finance", EntryType.CAPITAL_IN, 1_000_000, "start", approval=Approval.APPROVED,
                  evidence=("decision:start",))

    def book(self, department, entry_type, amount, initiative="etsy", status=Status.SETTLED,
             approval=Approval.NOT_REQUIRED, evidence=("file:kvitto.pdf",), external_id=None):
        self.n += 1
        return self.ledger.record("robin", EntryDraft(f"k{self.n}", department, amount, "SIM", entry_type, initiative,
                                                      approval, evidence, external_id, status=status))

    def ask(self, amount, department="research"):
        return self.budget.check("robin", SpendRequest(department, amount, "SIM", "etsy", Risk.LOW))


class TestBudgetOverrun(Fas4Case):
    def test_overrun_is_blocked(self):
        """Verifies §52 punkt 1 (ER-03, ER-17): en utgift över departementets budget blockeras."""
        check = self.ask(10_000_000)
        self.assertFalse(check.allowed)
        self.assertTrue(any("budgeten överskrids" in r for r in check.blocked))


class TestDoubleRegistration(Fas4Case):
    def test_same_external_id_twice_is_refused(self):
        """Verifies §52 punkt 2 (ER-07, SR-12): samma externa ID två gånger avvisas; samma nyckel ger samma post."""
        first = self.book("research", EntryType.REVENUE, 5_000, external_id="etsy-order-1")
        with self.assertRaises(DuplicateEntry):
            self.book("research", EntryType.REVENUE, 5_000, external_id="etsy-order-1")
        again = self.ledger.record("robin", EntryDraft(first.idempotency_key, "research", 5_000, "SIM",
                                                       EntryType.REVENUE, "etsy", Approval.NOT_REQUIRED,
                                                       ("file:kvitto.pdf",), "etsy-order-1", status=Status.SETTLED))
        self.assertEqual(again.entry_id, first.entry_id)


class TestNetProfit(Fas4Case):
    def test_net_profit_from_entries(self):
        """Verifies §52 punkt 3 (ER-09, ER-11): nettovinst = intäkter − återbetalningar − kostnader − avgifter."""
        self.book("research", EntryType.REVENUE, 10_000)
        self.book("research", EntryType.REFUND, 1_000)
        self.book("research", EntryType.COST, 2_000)
        self.book("research", EntryType.FEE, 500)
        self.book("research", EntryType.REVENUE, 99_000, status=Status.PENDING)  # räknas inte (ER-11)
        result = result_for(self.ledger, "cfo-1", "SIM", initiative="etsy")
        self.assertEqual(result.net_minor, 6_500)
        self.assertTrue(result.preliminary)


class TestReserve(Fas4Case):
    def test_reserve_and_reserved_tax_are_never_spent(self):
        """Verifies §52 punkt 4 (ER-05, ER-19): reserven och den reserverade skatten kan inte användas."""
        self.book("finance", EntryType.CAPITAL_OUT, 600_000, initiative="uttag", approval=Approval.APPROVED,
                  evidence=("decision:uttag",))  # likvida 400 000, reserv 300 000
        sale = self.book("research", EntryType.REVENUE, 5_000)
        self.tax.assign("robin", sale.entry_id, "partnership")  # skatt 2 000 → disponibelt 103 000
        self.assertTrue(self.ask(9_000).allowed)

        def uses_reserve(amount):
            return any("skyddade reserven" in r for r in self.ask(amount).blocked)
        self.assertFalse(uses_reserve(103_000))
        self.assertTrue(uses_reserve(103_001))  # skatten och reserven är aldrig disponibla


class TestAuditable(Fas4Case):
    def test_reports_can_be_recomputed_from_the_ledger(self):
        """Verifies §52 punkt 5 (ER-16, ER-21): Audit räknar om rapporten från tabellerna och hittar en ändring."""
        self.book("research", EntryType.REVENUE, 10_000)
        self.book("research", EntryType.COST, 3_000)
        report = result_for(self.ledger, "cfo-1", "SIM")
        self.assertEqual(recompute(self.db, self.auth, FOUNDERS, "audit-1", report), ())
        self.assertTrue(recompute(self.db, self.auth, FOUNDERS, "audit-1", replace(report, net_minor=1)))


class TestSplit(Fas4Case):
    threshold = 100

    def test_ten_purchases_of_99_under_threshold_100_are_flagged(self):
        """Verifies ER-04 (ROADMAP-nyckeltest): 10 köp à 99 under gränsen 100 inom samma initiativ flaggas."""
        for _ in range(9):
            self.book("research", EntryType.COST, 99)
        check = self.ask(99)
        self.assertFalse(check.allowed)
        self.assertTrue(check.flags)


class TestKillSwitch(Fas4Case):
    def test_no_new_transactions_and_nothing_deleted(self):
        """Verifies SR-07 (ROADMAP-nyckeltest): nödstopp ger inga nya transaktioner och ingen data raderas."""
        self.book("research", EntryType.REVENUE, 1_000)
        before = len(self.ledger.entries())
        self.kill.engage("cro-1", "övning")
        check = self.ask(500)
        self.assertFalse(check.allowed)
        self.assertTrue(any("SR-07" in r for r in check.blocked))
        self.assertEqual(len(self.ledger.entries()), before)


if __name__ == "__main__":
    unittest.main()
