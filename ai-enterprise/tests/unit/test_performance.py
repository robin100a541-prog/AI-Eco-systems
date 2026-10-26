"""Tester för prestationsmätning per roll (Fas 5c). Verifierar FR-19, §31, §33 och FR-03."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.evaluation import PROFILES, ForecastLog, IncidentLog, PerformanceError, PerformanceReview
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.orchestration import TaskBoard
from aie.risk import KillSwitch

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})


class PerformanceCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.clock = lambda: "2026-11-01T12:00:00+00:00"
        self.start()
        self.add("ceo-1", "ceo")
        for agent_id, role in (("cfo-1", "cfo"), ("cro-1", "cro"), ("comp-1", "compliance"), ("audit-1", "auditor")):
            self.add(agent_id, role)
        self.add("lead-1", "research_lead", "ceo-1")
        self.add("res-1", "researcher", "lead-1")
        self.add("res-2", "researcher", "lead-1")

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.kill = KillSwitch(self.db, self.registry, self.permissions, self.audit, FOUNDERS)
        self.engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit, gates=(self.kill,))
        departments = {m.department for m in self.permissions.roles.values()}
        self.ledger = Ledger(self.db, self.engine, departments, FOUNDERS, self.audit, approval_threshold=10_000)
        self.incidents = IncidentLog(self.db, self.registry, self.permissions, self.audit, FOUNDERS)
        self.forecasts = ForecastLog(self.db, self.registry, self.permissions, self.audit, FOUNDERS, self.ledger,
                                     self.clock)
        self.tasks = TaskBoard(self.db, self.registry, self.engine, FOUNDERS)
        self.perf = PerformanceReview(self.db, self.registry, self.permissions, self.audit, FOUNDERS, self.incidents,
                                      self.forecasts, self.tasks, self.ledger, clock=self.clock)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def keys(self, agent_id):
        return [m.key for m in self.perf.scorecard(agent_id).measures]


class TestRoleProfiles(PerformanceCase):
    def test_each_role_is_measured_on_its_mission(self):
        """Verifies FR-19 och §31: varje roll har egna mått; kontrollfunktioner mäts aldrig på intäkt."""
        self.assertEqual(set(PROFILES), {m for m in self.permissions.roles})
        for agent_id in ("cfo-1", "cro-1", "comp-1", "audit-1", "res-1"):
            with self.subTest(agent=agent_id):
                self.assertNotIn("economic_contribution", self.keys(agent_id))
        self.assertIn("economic_contribution", self.keys("ceo-1"))
        self.assertIn("economic_contribution", self.keys("lead-1"))
        self.assertIn("risk_identification", self.keys("cro-1"))
        self.assertEqual(self.keys("audit-1"), ["error_handling", "compliance", "incidents"])

    def test_no_total_score_and_unmeasured_aspects_are_listed(self):
        """Verifies §31: ingen sammanvägd poäng; det som inte kan mätas ännu syns."""
        card = self.perf.scorecard("res-1")
        self.assertFalse(hasattr(card, "total"))
        self.assertIn("Kvalitet", card.not_measured)
        self.assertIn("Mäts inte ännu", card.describe()[-1])


class TestMeasures(PerformanceCase):
    def test_goal_fulfillment_from_tasks(self):
        """Verifies FR-19: måluppfyllelse räknas från uppgifterna agenten äger; avbrutna räknas inte."""
        ids = [self.tasks.create("yorgo", f"uppgift {n}").task_id for n in range(4)]
        for task_id in ids:
            self.tasks.assign("yorgo", task_id, "res-1")
        for task_id in ids[:2]:
            self.tasks.start("res-1", task_id)
            self.tasks.complete("res-1", task_id, "klar")
        self.tasks.cancel("yorgo", ids[3], "behövs inte")
        m = self.perf.scorecard("res-1").measure("goal_fulfillment")
        self.assertEqual((m.value, len(m.evidence)), (6_666, 3))

    def test_forecast_precision_with_trend(self):
        """Verifies FR-19 och §31: prognosprecisionen kommer från prognosloggen, med trend över tid."""
        for n, actual in enumerate((50, 60, 95, 100)):
            f = self.forecasts.make("res-1", f"kunder {n}", "count", "st", 100, "2026-11-30")
            self.forecasts.record_outcome("lead-1", f.forecast_id, actual)
        m = self.perf.scorecard("res-1").measure("forecast_precision")
        self.assertEqual(m.value, 2_375)
        self.assertIn("från 4500 till 250 bp", m.detail)
        self.assertFalse(m.higher_is_better)

    def test_economic_contribution_by_department(self):
        """Verifies FR-19: ekonomiskt bidrag är ledgerns nettovinst för departementet (CEO: hela företaget)."""
        for key, dept, kind, amount in (("i1", "research", EntryType.REVENUE, 5_000),
                                        ("k1", "research", EntryType.COST, 1_000),
                                        ("k2", "finance", EntryType.COST, 300)):
            self.ledger.record("robin", EntryDraft(key, dept, amount, "SIM", kind, "x", Approval.NOT_REQUIRED,
                                                   ("decision:1",), status=Status.SETTLED))
        self.assertEqual(self.perf.scorecard("lead-1").measure("economic_contribution").value, 4_000)
        self.assertEqual(self.perf.scorecard("ceo-1").measure("economic_contribution").value, 3_700)

    def test_compliance_counts_only_attempts_outside_the_mandate(self):
        """Verifies FR-19 och §33: bara försök utanför mandatet räknas; nekanden på grund av nödstopp räknas inte."""
        self.engine.check("res-1", "ledger.read")  # utanför mandatet
        self.kill.engage("cro-1", "övning")
        self.engine.check("res-1", "research.search")  # i mandatet, nekas av nödstoppet
        m = self.perf.scorecard("res-1").measure("compliance")
        self.assertEqual((m.value, len(m.evidence)), (1, 1))
        self.assertEqual(self.perf.scorecard("res-2").measure("compliance").value, 0)


class TestFairness(PerformanceCase):
    def fill(self, incident_id):
        for key, value in (("department", "research"), ("agents", ["res-2"]), ("goal", "g"), ("forecast", "f"),
                           ("actions", "a"), ("outcome", "o"), ("economic_impact", {"amount_minor": 0, "currency": "SIM"}),
                           ("deviation", "d"), ("root_cause", "r"), ("contributing", "c"), ("corrective", "k"),
                           ("preventive", "p"), ("follow_up_owner", "comp-1")):
            self.incidents.record("lead-1", incident_id, key, value)

    def test_finding_errors_is_credited_never_penalized(self):
        """Verifies §31 och §33: att rapportera fel ger ett bättre värde, aldrig ett sämre."""
        before = self.perf.scorecard("audit-1")
        for n in range(3):
            self.incidents.open("audit-1", f"avvikelse {n}")
        after = self.perf.scorecard("audit-1")
        self.assertEqual((before.measure("error_handling").value, after.measure("error_handling").value), (0, 3))
        self.assertEqual(after.measure("incidents").value, 0)
        self.assertEqual(self.perf.scorecard("cro-1").measure("risk_identification").value, 0)
        self.kill.engage("cro-1", "misstänkt fel")
        self.assertEqual(self.perf.scorecard("cro-1").measure("risk_identification").value, 1)

    def test_only_verified_incidents_count_against_the_involved(self):
        """Verifies §33: en incident räknas mot en involverad agent först när den är verifierad."""
        incident = self.incidents.open("res-1", "fel pris")
        self.fill(incident.incident_id)
        m = self.perf.scorecard("res-2").measure("incidents")
        self.assertEqual(m.value, 0)
        self.assertIn("1 under utredning", m.detail)
        self.incidents.record("audit-1", incident.incident_id, "verification", "rättat och kontrollerat")
        self.assertEqual(self.perf.scorecard("res-2").measure("incidents").value, 1)
        self.assertEqual(self.perf.scorecard("res-1").measure("incidents").value, 0)  # rapportören


class TestReviews(PerformanceCase):
    def test_review_is_a_stored_snapshot_that_never_changes(self):
        """Verifies FR-19 och FR-03: en bedömning sparas med underlag och kan inte ändras eller raderas."""
        review = self.perf.review("lead-1", "res-1", "månadsgenomgång")
        self.assertEqual(review.scorecard["agent_id"], "res-1")
        self.assertIn("compliance", [m["key"] for m in review.scorecard["measures"]])
        for sql in ("UPDATE performance_reviews SET note = 'x'", "DELETE FROM performance_reviews"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)
        self.db.close()
        self.start()
        self.assertEqual(len(self.perf.reviews("res-1")), 1)

    def test_who_reviews_and_no_state_change(self):
        """Verifies FR-19 och §33: ingen bedömer sig själv, arbetsagenter bedömer inte, tillståndet ändras inte."""
        for reviewer in ("res-1", "res-2"):
            with self.subTest(reviewer=reviewer), self.assertRaises(PerformanceError):
                self.perf.review(reviewer, "res-1")
        with self.assertRaises(PerformanceError):
            self.perf.review("lead-1", "lead-1")
        self.perf.review("yorgo", "res-1")
        self.assertEqual(self.registry.get("res-1").state, S.ACTIVE)


if __name__ == "__main__":
    unittest.main()
