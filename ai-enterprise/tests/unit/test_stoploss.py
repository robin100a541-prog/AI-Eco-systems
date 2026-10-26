"""Tester för stop-loss (Fas 4e-1). Verifierar ER-13, §26, ER-02, ER-09 och FR-03.

Repots gränser: START_CAPITAL 1 000 000, MINIMUM_RESERVE 300 000, MAX_TOTAL_DRAWDOWN 20 %,
MAX_SINGLE_EXPERIMENT_LOSS 50 000. Research har budget 50 000.
"""
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, load_budgets
from aie.config import load_config
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.risk import StopLoss, StopLossError

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
T = EntryType


def spend(department="research", initiative="ny-kanal", amount=1_000):
    return SpendRequest(department, amount, "SIM", initiative, Risk.LOW)


class StopLossCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.departments = {m.department for m in self.permissions.roles.values()}
        self.limits = load_config(ROOT / "config").risk
        self.budgets = load_budgets(ROOT / "config", self.departments, self.limits)
        self.n = 0
        self.start()
        self.book(self.limits.start_capital.amount_minor, T.CAPITAL_IN, department="finance", initiative="start")

    def start(self, limits=None):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        engine = AuthorizationEngine(self.permissions, AgentRegistry(self.permissions, self.db), "sim", self.audit)
        self.ledger = Ledger(self.db, engine, self.departments, FOUNDERS, self.audit, approval_threshold=10_000)
        self.stoploss = StopLoss(self.db, self.ledger, limits or self.limits, self.budgets, self.audit, FOUNDERS)
        self.budget = BudgetEngine(self.ledger, limits or self.limits, self.budgets, self.audit, gates=(self.stoploss,))

    def book(self, amount, kind=T.COST, status=Status.SETTLED, department="research", initiative="etsy"):
        self.n += 1
        approval = Approval.APPROVED if kind is T.CAPITAL_IN else (
            Approval.UNAPPROVED if amount > 10_000 else Approval.NOT_REQUIRED)
        return self.ledger.record("robin", EntryDraft(
            f"k{self.n}", department, amount, "SIM", kind, initiative, approval, ("decision:test",), status=status))


class TestTriggers(StopLossCase):
    def test_healthy_company_has_no_breach(self):
        """Verifies ER-13: med orört startkapital är ingen gräns nådd."""
        self.assertEqual(self.stoploss.breaches(), ())
        self.assertEqual(self.stoploss.evaluate(), ())
        self.assertTrue(self.budget.check("x", spend()).allowed)

    def test_experiment_loss_stops_that_initiative_only(self):
        """Verifies ER-13 (§26): en förlust på MAX_SINGLE_EXPERIMENT_LOSS stoppar initiativet, inte allt annat."""
        self.book(50_000, T.REFUND, initiative="etsy")  # återbetalningar: förlust utan att röra budgeten
        (trip,) = self.stoploss.evaluate()
        self.assertEqual((trip.scope_kind, trip.scope_value, trip.limit_name),
                         ("initiative", "etsy", "MAX_SINGLE_EXPERIMENT_LOSS"))
        blocked = self.budget.check("x", spend(initiative="etsy"))
        self.assertFalse(blocked.allowed)
        self.assertTrue(any("ER-13" in r for r in blocked.blocked))
        self.assertTrue(self.budget.check("x", spend(initiative="gumroad")).allowed)

    def test_department_budget_reached_stops_department(self):
        """Verifies ER-13: när departementets budget är nådd stoppas nya åtaganden där."""
        self.book(50_000, status=Status.PENDING, department="research", initiative="stor-order")
        (trip,) = self.stoploss.evaluate()
        self.assertEqual((trip.scope_kind, trip.scope_value, trip.limit_name), ("department", "research", "budget"))
        self.assertFalse(self.budget.check("x", spend(department="research", initiative="annat")).allowed)
        self.assertTrue(self.budget.check("x", spend(department="executive", initiative="annat")).allowed)

    def test_total_drawdown_stops_everything(self):
        """Verifies ER-13: MAX_TOTAL_DRAWDOWN (20 %) stoppar nya åtaganden i hela företaget."""
        self.book(200_000, T.CAPITAL_OUT, department="finance", initiative="uttag")
        names = {t.limit_name for t in self.stoploss.evaluate()}
        self.assertIn("MAX_TOTAL_DRAWDOWN", names)
        for department in ("research", "executive"):
            self.assertFalse(self.budget.check("x", spend(department=department, initiative="z")).allowed)

    def test_reserve_limit_trips(self):
        """Verifies ER-13 och ER-05: när likvida medel minus åtaganden når reserven utlöses stop-loss."""
        self.book(690_000, T.CAPITAL_OUT, department="finance", initiative="uttag")
        self.book(10_000, status=Status.PENDING, department="research", initiative="order")
        self.assertIn("MINIMUM_RESERVE", {t.limit_name for t in self.stoploss.evaluate()})

    def test_missing_limit_counts_as_reached(self):
        """Verifies ER-02: saknas MAX_TOTAL_DRAWDOWN eller MAX_SINGLE_EXPERIMENT_LOSS räknas gränsen som nådd."""
        self.start(replace(self.limits, max_total_drawdown=None, max_single_experiment_loss=None))
        self.book(1, T.REFUND, initiative="liten")
        breaches = {(b.limit_name, b.limit_value) for b in self.stoploss.breaches()}
        self.assertIn(("MAX_TOTAL_DRAWDOWN", "saknas"), breaches)
        self.assertIn(("MAX_SINGLE_EXPERIMENT_LOSS", "saknas"), breaches)

    def test_evaluate_is_idempotent(self):
        """Verifies ER-13: en gräns som redan är utlöst ger ingen ny utlösning."""
        self.book(50_000, T.REFUND)
        self.assertEqual(len(self.stoploss.evaluate()), 1)
        self.assertEqual(self.stoploss.evaluate(), ())
        self.assertEqual(len(self.stoploss.active()), 1)


class TestConsequences(StopLossCase):
    def test_exposure_and_obligations_are_kept_not_cancelled(self):
        """Verifies ER-13 (§26): exponering räknas, förpliktelser listas och ingen post avbryts eller raderas."""
        order = self.book(8_000, status=Status.PENDING, department="research", initiative="etsy")
        self.book(50_000, T.REFUND, initiative="etsy")
        (trip,) = self.stoploss.evaluate()
        self.assertEqual(trip.exposure, {"pending_outflow_minor": 8_000, "pending_entry_ids": [order.entry_id]})
        self.assertIs(self.ledger.get(order.entry_id).status, Status.PENDING)  # hanteras, ignoreras inte
        self.ledger.set_status("robin", order.entry_id, Status.SETTLED, "betald enligt avtal")  # går fortfarande

    def test_responsible_are_informed_in_audit(self):
        """Verifies ER-13: riskfunktionen, CFO och departementschefen informeras via revisionsloggen."""
        self.book(50_000, status=Status.PENDING, department="research", initiative="stor-order")
        (trip,) = self.stoploss.evaluate()
        self.assertEqual(trip.notified, ("role:cro", "role:cfo", "head:research"))
        entry = next(e for e in self.audit.entries() if e.action == "stoploss.tripped")
        self.assertEqual(entry.details["notified"], ["role:cro", "role:cfo", "head:research"])
        self.assertTrue(self.audit.verify().ok)


class TestResume(StopLossCase):
    def setUp(self):
        super().setUp()
        self.book(50_000, T.REFUND, initiative="etsy")
        (self.trip,) = self.stoploss.evaluate()

    def test_resume_needs_two_founders_a_plan_and_a_fixed_situation(self):
        """Verifies ER-13 (D-029): nytt godkännande krävs: plan, läget åtgärdat och två olika grundare."""
        with self.assertRaises(StopLossError) as ctx:
            self.stoploss.approve_resume("yorgo", self.trip.trip_id, "sälj mer")
        self.assertIn("fortfarande nådd", str(ctx.exception))
        self.book(1, T.REVENUE, initiative="etsy")  # förlusten nu under gränsen
        for actor, plan in (("cfo-1", "plan"), ("yorgo", " ")):
            with self.subTest(actor=actor), self.assertRaises(StopLossError):
                self.stoploss.approve_resume(actor, self.trip.trip_id, plan)
        trip = self.stoploss.approve_resume("yorgo", self.trip.trip_id, "halvera annonsbudgeten, ny prisnivå")
        self.assertTrue(trip.active)
        self.assertFalse(self.budget.check("x", spend(initiative="etsy")).allowed)
        with self.assertRaises(StopLossError):
            self.stoploss.approve_resume("yorgo", self.trip.trip_id, "igen")
        trip = self.stoploss.approve_resume("robin", self.trip.trip_id, "instämmer")
        self.assertFalse(trip.active)
        self.assertTrue(self.budget.check("x", spend(initiative="etsy")).allowed)

    def test_survives_restart_and_is_append_only(self):
        """Verifies FR-03 och ER-13: utlösningen gäller efter omstart och kan inte ändras eller raderas."""
        self.db.close()
        self.start()
        self.assertFalse(self.budget.check("x", spend(initiative="etsy")).allowed)
        for sql in ("DELETE FROM stop_loss_trips", "UPDATE stop_loss_trips SET limit_name = 'x'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)


class TestGateFailure(StopLossCase):
    def test_gate_that_cannot_decide_blocks(self):
        """Verifies §59: om en spärr kraschar blir svaret nej."""
        class Broken:
            def spend_block_reasons(self, request):
                raise RuntimeError("trasig")
        engine = BudgetEngine(self.ledger, self.limits, self.budgets, self.audit, gates=(Broken(),))
        result = engine.check("x", spend())
        self.assertFalse(result.allowed)
        self.assertTrue(any("kunde inte avgöra" in r for r in result.blocked))


if __name__ == "__main__":
    unittest.main()
