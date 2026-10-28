"""Tester för lärdomsregistret (Fas 5d). Verifierar FR-17, §27, §29, §30 och §53."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import load_permissions
from aie.evaluation import CAUSES, ForecastLog, IncidentLog, LessonError, LessonRegistry
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})


class LessonCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.start()
        self.add("ceo-1", "ceo")
        self.add("audit-1", "auditor")
        self.add("lead-1", "research_lead", "ceo-1")
        self.add("res-1", "researcher", "lead-1")

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        clock = lambda: "2026-11-01T12:00:00+00:00"  # noqa: E731
        self.incidents = IncidentLog(self.db, self.registry, self.permissions, self.audit, FOUNDERS)
        self.forecasts = ForecastLog(self.db, self.registry, self.permissions, self.audit, FOUNDERS, clock=clock)
        self.lessons = LessonRegistry(self.db, self.registry, self.permissions, self.audit, FOUNDERS,
                                      self.incidents, self.forecasts)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def forecast_with_outcome(self, n):
        f = self.forecasts.make("res-1", f"försäljning {n}", "count", "st", 10, "2026-11-30")
        self.forecasts.record_outcome("lead-1", f.forecast_id, 9)
        return f"forecast:{f.forecast_id}"

    def hypothesis(self):
        incident = self.incidents.open("res-1", "annonserna togs bort")
        return self.lessons.propose("res-1", "Etsy-annonser behöver AI-märkning", "predictable_error", "research",
                                    (f"incident:{incident.incident_id}",))


class TestStatuses(LessonCase):
    def test_the_five_statuses_and_seven_causes_of_section_29(self):
        """Verifies FR-17 och §29: fem verifieringsstatusar och sju orsakstyper."""
        lesson = self.hypothesis()
        self.assertEqual(lesson.status, "hypothesis")
        self.assertEqual(len(CAUSES), 7)
        with self.assertRaises(LessonError):
            self.lessons.propose("res-1", "x", "otur", "research", ("test:a",))
        with self.assertRaises(LessonError):
            self.lessons.propose("res-1", "x", "random", "research", ())  # §30: källa krävs
        with self.assertRaises(LessonError):
            self.lessons.propose("res-1", "x", "random", "research", ("incident:999",))

    def test_full_path_to_operational_rule_step_by_step(self):
        """Verifies FR-17 och §53: hypotes → preliminär → testad → reproducerbar → regel, ett steg i taget."""
        lesson = self.hypothesis()
        lid = lesson.lesson_id
        with self.assertRaises(LessonError):
            self.lessons.promote("res-1", lid, "jag tror på den")  # den som föreslog granskar inte
        lesson = self.lessons.promote("lead-1", lid, "stämmer med Etsys villkor")
        self.assertEqual(lesson.status, "preliminary")
        with self.assertRaises(LessonError):
            self.lessons.promote("lead-1", lid, "testad")  # inget test än
        self.lessons.add_evidence("res-1", lid, (self.forecast_with_outcome(1),), "märkta annonser låg kvar")
        self.assertEqual(self.lessons.promote("audit-1", lid, "ett test").status, "tested")
        with self.assertRaises(LessonError):
            self.lessons.promote("audit-1", lid, "reproducerbar")  # bara ett test
        self.lessons.add_evidence("res-1", lid, ("test:etsy-november",), "andra omgången")
        self.assertEqual(self.lessons.promote("audit-1", lid, "två test").status, "reproducible")
        with self.assertRaises(LessonError):
            self.lessons.promote("ceo-1", lid, "gör den till regel")  # kräver grundarna
        with self.assertRaises(LessonError):
            self.lessons.vote_rule("ceo-1", lid, "ok")  # bara grundare
        self.assertEqual(self.lessons.vote_rule("robin", lid, "ok").status, "operational_rule")  # D-049
        with self.assertRaises(LessonError):
            self.lessons.vote_rule("yorgo", lid, "igen")  # redan en regel
        self.assertEqual([x.lesson_id for x in self.lessons.rules()], [lid])

    def test_unconfirmed_hypothesis_never_becomes_a_rule(self):
        """Verifies §53: en obekräftad hypotes blir inte automatiskt en obligatorisk regel."""
        lesson = self.hypothesis()
        with self.assertRaises(LessonError):
            self.lessons.vote_rule("robin", lesson.lesson_id, "kör")
        with self.assertRaises(LessonError):
            self.lessons.require_rule(lesson.lesson_id)
        self.assertEqual(self.lessons.rules(), ())

    def test_forecast_without_outcome_is_not_a_test(self):
        """Verifies FR-17 och §29: en prognos räknas som test först när utfallet finns."""
        lesson = self.hypothesis()
        f = self.forecasts.make("res-1", "x", "count", "st", 1, "2026-11-30")
        with self.assertRaises(LessonError):
            self.lessons.add_evidence("res-1", lesson.lesson_id, (f"forecast:{f.forecast_id}",), "väntar")


class TestHistory(LessonCase):
    def test_demote_reject_and_nothing_is_rewritten(self):
        """Verifies FR-17 och §30: sänkning och avvisning är händelser; inget kan ändras eller raderas."""
        lesson = self.hypothesis()
        lid = lesson.lesson_id
        self.lessons.promote("lead-1", lid, "rimlig")
        lesson = self.lessons.demote("audit-1", lid, "hypothesis", "nytt underlag talar emot", ("test:dec",))
        self.assertEqual(lesson.status, "hypothesis")
        self.assertEqual(self.lessons.reject("audit-1", lid, "slumpmässigt utfall").status, "rejected")
        with self.assertRaises(LessonError):
            self.lessons.promote("lead-1", lid, "igen")
        for sql in ("UPDATE lessons SET statement = 'x'", "DELETE FROM lessons", "DELETE FROM lesson_events",
                    "UPDATE lesson_events SET note = 'x'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)
        self.db.close()
        self.start()
        self.assertEqual([e.event for e in self.lessons.get(lid).events], ["promote", "demote", "reject"])

    def test_from_incident_and_reviewers(self):
        """Verifies FR-17 och §27: en lärdom kan skapas från en incidents grundorsak; arbetsagenter granskar inte."""
        incident = self.incidents.open("res-1", "fel pris")
        self.incidents.record("lead-1", incident.incident_id, "root_cause", "valutan räknades fel")
        lesson = self.lessons.from_incident("lead-1", incident.incident_id, "bad_execution")
        self.assertEqual((lesson.statement, lesson.sources), ("valutan räknades fel", (f"incident:{incident.incident_id}",)))
        self.add("res-2", "researcher", "lead-1")
        with self.assertRaises(LessonError):
            self.lessons.promote("res-2", lesson.lesson_id, "ok")


if __name__ == "__main__":
    unittest.main()
