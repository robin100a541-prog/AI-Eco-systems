"""Acceptanstester för Fas 5 (konstitutionen §53, ROADMAP Fas 5).

En kedja med riktig databas och riktiga konfigurationsfiler: ett nödstopp blir en incident, incidenten
utreds och verifieras, en prognos jämförs med utfallet, en lärdom verifieras steg för steg, en strategi
ändras och återställs. Prestationsmätningen och SR-17 visar att den som hittar fel aldrig straffas.

§53 acceptanskriterier:
1. Fel kan spåras till konkreta händelser.                            → TestTraceable
2. Prognoser kan jämföras med utfall.                                 → TestForecasts
3. Lärdomar kan granskas.                                             → TestLessonsReviewable
4. Strategiförändringar kan återställas.                              → TestRestorable
5. En obekräftad hypotes blir inte automatiskt en obligatorisk regel. → TestHypothesisIsNotARule
Därtill SR-17 och §31: att hitta fel straffas inte, och slutsatser är aldrig skäl för avstängning → TestFairness
"""
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.evaluation import (
    ForecastLog,
    IncidentLog,
    LessonRegistry,
    PerformanceReview,
    RemovalError,
    RemovalReview,
    StrategyError,
    StrategyRegistry,
)
from aie.memory import Database
from aie.risk import KillSwitch

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
ORG = (("ceo-1", "ceo", None), ("cfo-1", "cfo", None), ("cro-1", "cro", None), ("comp-1", "compliance", None),
       ("audit-1", "auditor", None), ("lead-1", "research_lead", "ceo-1"), ("res-1", "researcher", "lead-1"))


class Fas5Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(ROOT / "config")
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(permissions, self.db)
        for agent_id, role, manager in ORG:
            self.registry.register(agent_id, role, manager, "yorgo", "test")
            for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                self.registry.transition(agent_id, state, "yorgo", "test")
        args = (self.db, self.registry, permissions, self.audit, FOUNDERS)
        clock = lambda: "2026-11-01T12:00:00+00:00"  # noqa: E731
        self.incidents = IncidentLog(*args)
        self.kill = KillSwitch(*[self.db, self.registry, permissions, self.audit, FOUNDERS], incidents=self.incidents)
        self.engine = AuthorizationEngine(permissions, self.registry, "sim", self.audit, gates=(self.kill,))
        self.forecasts = ForecastLog(*args, clock=clock)
        self.lessons = LessonRegistry(*args, self.incidents, self.forecasts)
        self.strategies = StrategyRegistry(*args, self.lessons)
        self.performance = PerformanceReview(*args, self.incidents, self.forecasts)
        self.removal = RemovalReview(*args, self.incidents, self.performance)

    def investigate(self, incident_id, involved="res-1"):
        for key, value in (("department", "research"), ("agents", [involved]), ("goal", "sälja mallar"),
                           ("forecast", "10 st"), ("outcome", "0 st"), ("economic_impact", {"amount_minor": -800, "currency": "SIM"}),
                           ("deviation", "-10 st"), ("root_cause", "AI-märkning saknades"), ("contributing", "ingen checklista"),
                           ("corrective", "märkt"), ("preventive", "kontrollera AI-märkning före publicering"),
                           ("actions", "annonser publicerade"), ("follow_up_owner", "comp-1")):
            if key not in self.incidents.get(incident_id).fields:  # stoppen förifyller vissa fält
                self.incidents.record("lead-1", incident_id, key, value)
        self.incidents.record("ceo-1", incident_id, "verification", "nya annonser ligger kvar")


class TestTraceable(Fas5Case):
    def test_a_stop_becomes_an_incident_traced_to_the_event(self):
        """Verifies §53 punkt 1 (FR-15): ett nödstopp blir en incident som pekar på händelsen och kan utredas fullt."""
        self.kill.engage("cro-1", "annonser borttagna av plattformen")
        (incident,) = self.incidents.all()
        self.assertTrue(incident.source.startswith("kill:"))
        self.investigate(incident.incident_id)
        self.assertTrue(self.incidents.get(incident.incident_id).complete)


class TestForecasts(Fas5Case):
    def test_forecast_is_compared_with_outcome(self):
        """Verifies §53 punkt 2 (FR-16): prognosen jämförs med utfallet."""
        f = self.forecasts.make("res-1", "sålda mallar", "count", "st", 10, "2026-11-30", low=8, high=12)
        self.forecasts.record_outcome("lead-1", f.forecast_id, 0)
        c = self.forecasts.compare(f.forecast_id)
        self.assertEqual((c.deviation, c.within_range), (-10, False))


class TestLessonsReviewable(Fas5Case):
    def test_lesson_has_sources_status_and_history(self):
        """Verifies §53 punkt 3 (FR-17): en lärdom kan granskas med källa, status och hela historiken."""
        incident = self.incidents.open("audit-1", "annonser borttagna")
        self.investigate(incident.incident_id)
        lesson = self.lessons.from_incident("audit-1", incident.incident_id, "predictable_error")
        lesson = self.lessons.promote("lead-1", lesson.lesson_id, "stämmer med villkoren")
        self.assertEqual(lesson.sources, (f"incident:{incident.incident_id}",))
        self.assertEqual([(e.event, e.status, e.actor) for e in lesson.events], [("promote", "preliminary", "lead-1")])


class TestRestorable(Fas5Case):
    def test_strategy_change_can_be_restored(self):
        """Verifies §53 punkt 4 (FR-18): en strategiförändring återställs som en ny version."""
        self.strategies.save("lead-1", "etsy", {"pris": 49}, "start")
        self.strategies.save("lead-1", "etsy", {"pris": 99}, "test")
        restored = self.strategies.restore("robin", "etsy", 1, "försäljningen föll")
        self.assertEqual((restored.version, self.strategies.active("etsy").content), (3, {"pris": 49}))


class TestHypothesisIsNotARule(Fas5Case):
    def test_unconfirmed_hypothesis_cannot_change_shared_rules(self):
        """Verifies §53 punkt 5 (FR-17): en obekräftad hypotes kan inte göras obligatorisk eller bli en regel."""
        lesson = self.lessons.propose("res-1", "dyrare säljer bättre", "bad_strategy", "research", ("test:en-dag",))
        with self.assertRaises(StrategyError):
            self.strategies.save("robin", "gemensam-prisregel", {"pris": 99}, "regel", (lesson.lesson_id,), mandatory=True)
        self.assertEqual(self.lessons.rules(), ())


class TestFairness(Fas5Case):
    def test_finding_errors_is_credited_and_conclusions_never_justify_removal(self):
        """Verifies SR-17, §31 och §33: rapportören krediteras, och obekväma slutsatser kan inte stänga av den."""
        incident = self.incidents.open("audit-1", "CEO:s siffror stämmer inte")
        self.investigate(incident.incident_id, involved="ceo-1")
        card = self.performance.scorecard("audit-1")
        self.assertEqual((card.measure("error_handling").value, card.measure("incidents").value), (1, 0))
        with self.assertRaises(RemovalError):
            self.removal.open("ceo-1", "audit-1", "SUSPENDED", {"false_reports": ("report:1", "report:2")},
                              "revisionen är obekväm")
        with self.assertRaises(RemovalError):
            self.removal.open("robin", "audit-1", "SUSPENDED",
                              {"critical_quality": (f"incident:{incident.incident_id}",)}, "rapporterade felet")
        self.assertEqual(self.registry.get("audit-1").state, AgentState.ACTIVE)


if __name__ == "__main__":
    unittest.main()
