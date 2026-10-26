"""Tester för prognosloggen (Fas 5b). Verifierar FR-16, §20 steg 10, ER-11 och FR-03."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.evaluation import ForecastError, ForecastLog
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})


class Clock:
    def __init__(self, day="2026-11-01"):
        self.day = day

    def __call__(self):
        return f"{self.day}T12:00:00+00:00"


class ForecastCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.clock = Clock()
        self.start()
        self.add("ceo-1", "ceo")
        self.add("cfo-1", "cfo")
        self.add("lead-1", "research_lead", "ceo-1")
        self.add("res-1", "researcher", "lead-1")
        self.add("res-2", "researcher", "lead-1")

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        departments = {m.department for m in self.permissions.roles.values()}
        engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.ledger = Ledger(self.db, engine, departments, FOUNDERS, self.audit, approval_threshold=10_000)
        self.log = ForecastLog(self.db, self.registry, self.permissions, self.audit, FOUNDERS, self.ledger, self.clock)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def book(self, key, entry_type, amount, status=Status.SETTLED, initiative="etsy-mallar"):
        return self.ledger.record("robin", EntryDraft(key, "research", amount, "SIM", entry_type, initiative,
                                                      Approval.NOT_REQUIRED, ("decision:7",), status=status))

    def net_forecast(self, agent="res-1", expected=4_000, low=3_000, high=5_000, due="2026-11-30"):
        return self.log.make(agent, "netto för Etsy-mallar i november", "net", "SIM", expected, due,
                             low, high, initiative="etsy-mallar", decision="decision:7")


class TestLogging(ForecastCase):
    def test_forecast_is_logged_before_the_outcome(self):
        """Verifies FR-16: en prognos sparas med mått, enhet, värde, intervall, förfallodag och länk till beslutet."""
        f = self.net_forecast()
        self.assertEqual((f.agent, f.metric, f.unit, f.expected, f.low, f.high, f.due, f.decision),
                         ("res-1", "net", "SIM", 4_000, 3_000, 5_000, "2026-11-30", "decision:7"))
        self.assertIsNone(f.outcome)
        with self.assertRaises(ForecastError):  # efter förfallodagen är det ingen prognos
            self.net_forecast(due="2026-10-31")

    def test_invalid_forecasts_are_refused(self):
        """Verifies FR-16 och D-006: heltal, giltigt mått, valuta och initiativ för ledgermått, giltigt datum."""
        bad = (
            dict(metric="net", unit="SIM", expected=4.5, initiative="x"),
            dict(metric="net", unit="SIM", expected=4, initiative=None),
            dict(metric="net", unit="kr", expected=4, initiative="x"),
            dict(metric="mood", unit="st", expected=4),
            dict(metric="count", unit="st", expected=4, low=5),
            dict(metric="count", unit="st", expected=4, due="snart"),
            dict(metric="count", unit="st", expected=4, decision="beslut 7"),
        )
        for kwargs in bad:
            kwargs = {"due": "2026-11-30", **kwargs}
            with self.subTest(**kwargs), self.assertRaises(ForecastError):
                self.log.make("res-1", "x", **kwargs)
        self.registry.transition("res-2", S.SUSPENDED, "yorgo", "test")
        with self.assertRaises(ForecastError):
            self.log.make("res-2", "x", "count", "st", 1, "2026-11-30")


class TestNeverRewritten(ForecastCase):
    def test_revision_keeps_the_original_and_both_are_compared(self):
        """Verifies §20 steg 10: en revidering är en ny prognos; den ursprungliga finns kvar och jämförs."""
        original = self.net_forecast()
        revised = self.log.revise("res-1", original.forecast_id, 2_000, 1_000, 3_000)
        self.assertEqual((revised.revises, self.log.get(original.forecast_id).expected), (original.forecast_id, 4_000))
        with self.assertRaises(ForecastError):
            self.log.revise("res-1", original.forecast_id, 1)  # revidera den senaste
        with self.assertRaises(ForecastError):
            self.log.revise("res-2", revised.forecast_id, 1)  # någon annans prognos
        self.book("i1", EntryType.REVENUE, 3_000)
        self.book("k1", EntryType.COST, 500)
        self.clock.day = "2026-12-01"
        with self.assertRaises(ForecastError):
            self.log.revise("res-1", revised.forecast_id, 2_500)  # efter förfallodagen
        compared = {c.forecast.forecast_id: c for c in self.log.evaluate()}
        self.assertEqual(compared[original.forecast_id].deviation, -1_500)
        self.assertEqual(compared[revised.forecast_id].deviation, 500)

    def test_database_blocks_edit_and_delete(self):
        """Verifies FR-16: prognoser och utfall kan inte ändras eller raderas, inte ens med SQL."""
        f = self.log.make("res-1", "nya kunder", "count", "st", 10, "2026-11-30")
        self.log.record_outcome("lead-1", f.forecast_id, 8)
        for sql in ("UPDATE forecasts SET expected = 8", "DELETE FROM forecasts",
                    "UPDATE forecast_outcomes SET actual = 10", "DELETE FROM forecast_outcomes"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)
        self.db.close()
        self.start()
        self.assertEqual(self.log.get(f.forecast_id).outcome.actual, 8)  # FR-03

    def test_outcome_correction_is_a_new_entry_with_reason(self):
        """Verifies FR-16: ett utfall rättas med en ny post som pekar på det gamla och har en motivering."""
        f = self.log.make("res-1", "nya kunder", "count", "st", 10, "2026-11-30", low=8, high=12)
        self.log.record_outcome("lead-1", f.forecast_id, 7)
        with self.assertRaises(ForecastError):
            self.log.record_outcome("lead-1", f.forecast_id, 9)
        f = self.log.record_outcome("cfo-1", f.forecast_id, 9, "två kunder registrerades sent")
        first, second = f.outcomes
        self.assertEqual((second.corrects, f.outcome.actual), (first.outcome_id, 9))
        self.assertTrue(self.log.compare(f.forecast_id).within_range)


class TestAutomaticComparison(ForecastCase):
    def test_ledger_outcome_is_fetched_and_compared_with_evidence(self):
        """Verifies FR-16 och §20 steg 10: förfallna ledgerprognoser jämförs automatiskt med ledgern."""
        f = self.net_forecast()
        self.book("i1", EntryType.REVENUE, 6_000)
        self.book("a1", EntryType.FEE, 400)
        self.book("k1", EntryType.COST, 2_100)
        self.book("x1", EntryType.REVENUE, 99_999, initiative="annat")
        self.assertEqual(self.log.evaluate(), ())  # inte förfallen än
        self.clock.day = "2026-11-30"
        (c,) = self.log.evaluate()
        self.assertEqual((c.actual, c.deviation, c.error_bp, c.within_range), (3_500, -500, 1_250, True))
        self.assertEqual(c.forecast.outcome.source, "ledger")
        self.assertEqual(len(c.forecast.outcome.evidence), 3)
        self.assertIn("avvikelse -500", c.describe())
        self.assertEqual(self.log.evaluate(), ())  # inga dubbletter

    def test_preliminary_result_is_not_an_outcome(self):
        """Verifies ER-11: väntande poster gör resultatet preliminärt, så inget utfall sparas och prognosen är förfallen."""
        f = self.net_forecast()
        self.book("i1", EntryType.REVENUE, 6_000)
        self.book("k1", EntryType.COST, 1_000, status=Status.PENDING)
        self.clock.day = "2026-12-01"
        self.assertEqual(self.log.evaluate(), ())
        self.assertEqual([x.forecast_id for x in self.log.overdue()], [f.forecast_id])

    def test_reported_outcome_not_by_the_forecaster(self):
        """Verifies FR-16: den som gjorde prognosen rapporterar inte själv utfallet; arbetsagenter rapporterar inte."""
        f = self.log.make("res-1", "nya kunder", "count", "st", 10, "2026-11-30")
        for actor in ("res-1", "res-2"):
            with self.subTest(actor=actor), self.assertRaises(ForecastError):
                self.log.record_outcome(actor, f.forecast_id, 10)
        with self.assertRaises(ForecastError):  # ledgermått kommer från ledgern
            self.log.record_outcome("lead-1", self.net_forecast().forecast_id, 1)

    def test_accuracy_per_agent(self):
        """Verifies FR-16: träffsäkerheten per agent räknas från jämförelserna och förfallna prognoser."""
        a = self.log.make("res-1", "kunder", "count", "st", 10, "2026-11-30", low=9, high=11)
        b = self.log.make("res-1", "besök", "count", "st", 200, "2026-11-30", low=150, high=250)
        self.log.make("res-1", "recensioner", "count", "st", 5, "2026-11-15")
        self.log.record_outcome("lead-1", a.forecast_id, 10)
        self.log.record_outcome("lead-1", b.forecast_id, 100)
        self.clock.day = "2026-11-20"
        acc = self.log.accuracy("res-1")
        self.assertEqual((acc.compared, acc.within_range, acc.with_range, acc.mean_error_bp, acc.overdue),
                         (2, 1, 2, 2_500, 1))
        self.assertEqual(self.log.accuracy("res-2").compared, 0)


if __name__ == "__main__":
    unittest.main()
