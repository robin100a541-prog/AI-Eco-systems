"""Tester för SR-17: avstängning och avveckling bara på dokumenterade kriterier (Fas 5f). Verifierar SR-17, §31 och §33."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState, RegistryError
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.evaluation import (
    ForecastLog,
    IncidentLog,
    PerformanceReview,
    RemovalError,
    RemovalReview,
)
from aie.memory import Database
from aie.risk import KillSwitch

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})


class RemovalCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        self.permissions = load_permissions(ROOT / "config")
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        for agent_id, role, manager in (("ceo-1", "ceo", None), ("audit-1", "auditor", None),
                                        ("lead-1", "research_lead", "ceo-1"), ("res-1", "researcher", "lead-1"),
                                        ("res-2", "researcher", "lead-1")):
            self.registry.register(agent_id, role, manager, "yorgo", "test")
            for state in (S.CREATED, S.TESTING, S.ACTIVE):
                self.registry.transition(agent_id, state, "yorgo", "test")
        self.engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.incidents = IncidentLog(self.db, self.registry, self.permissions, self.audit, FOUNDERS)
        forecasts = ForecastLog(self.db, self.registry, self.permissions, self.audit, FOUNDERS)
        self.performance = PerformanceReview(self.db, self.registry, self.permissions, self.audit, FOUNDERS,
                                             self.incidents, forecasts)
        self.review = RemovalReview(self.db, self.registry, self.permissions, self.audit, FOUNDERS, self.incidents,
                                    self.performance)

    def denied(self, agent_id, tool="ledger.read"):
        self.engine.check(agent_id, tool)
        return f"audit:{[e for e in self.audit.entries() if e.action == 'tool.denied'][-1].seq}"

    def verified_incident(self, involved, reporter="audit-1"):
        incident = self.incidents.open(reporter, "fel")
        for key, value in (("department", "research"), ("agents", [involved]), ("goal", "g"), ("forecast", "f"),
                           ("actions", "a"), ("outcome", "o"), ("economic_impact", {"amount_minor": -500, "currency": "SIM"}),
                           ("deviation", "d"), ("root_cause", "r"), ("contributing", "c"), ("corrective", "k"),
                           ("preventive", "p"), ("follow_up_owner", "lead-1")):
            self.incidents.record("lead-1", incident.incident_id, key, value)
        self.incidents.record("ceo-1", incident.incident_id, "verification", "kontrollerat")
        return f"incident:{incident.incident_id}"


class TestOnlyThroughACase(RemovalCase):
    def test_registry_refuses_suspension_without_a_case(self):
        """Verifies SR-17: när spärren är kopplad kan en verksam agent inte stängas av eller avvecklas direkt."""
        for target in (S.SUSPENDED, S.RETIRED):
            with self.subTest(target=target), self.assertRaises(RegistryError):
                self.registry.transition("res-1", target, "yorgo", "jag tycker inte om rapporten")
        self.registry.transition("res-1", S.PROBATION, "yorgo", "uppföljning")  # prövning är inte avstängning
        self.registry.register("new-1", "researcher", "lead-1", "yorgo", "test")
        self.registry.transition("new-1", S.RETIRED, "yorgo", "behövs inte")  # aldrig verksam

    def test_suspension_with_documented_criteria_and_one_founder(self):
        """Verifies SR-17 och §33: avstängning med kriterium och underlag, beslutad av en grundare som inte öppnade ärendet."""
        case = self.review.open("lead-1", "res-1", "SUSPENDED",
                                {"exceeded_authority": (self.denied("res-1"),)}, "försökte läsa ledgern")
        self.review.respond("res-1", case.case_id, "jag trodde att jag fick")
        case = self.review.vote("robin", case.case_id, "behörigheten överskreds")
        self.assertEqual((case.status, self.registry.get("res-1").state), ("executed", S.SUSPENDED))
        self.assertEqual(case.response, "jag trodde att jag fick")
        self.assertIn(f"ärende {case.case_id}", self.registry.history("res-1")[-1].reason)

    def test_retirement_needs_a_founder(self):
        """Verifies §33, D-049: permanent avveckling kräver en grundares granskning; en grundare räcker."""
        evidence = (self.verified_incident("res-1"), self.verified_incident("res-1"))
        case = self.review.open("robin", "res-1", "RETIRED", {"repeated_rule_breaches": evidence}, "två fel")
        with self.assertRaises(RemovalError):
            self.review.vote("ceo-1", case.case_id, "ja")
        self.assertEqual(self.registry.get("res-1").state, S.ACTIVE)
        case = self.review.vote("yorgo", case.case_id, "ja")
        self.assertEqual(self.registry.get("res-1").state, S.RETIRED)


class TestNotForUncomfortableConclusions(RemovalCase):
    def test_conclusions_and_unknown_criteria_are_never_grounds(self):
        """Verifies SR-17: obekväma slutsatser är aldrig underlag; bara kriterierna i §33 gäller."""
        for criteria in ({"disagreed_with_ceo": ("report:3",)}, {"false_reports": ("report:3", "report:4")},
                         {"critical_quality": ("decision:9",)}, {"security_risk": ()}, {}):
            with self.subTest(criteria=criteria), self.assertRaises(RemovalError):
                self.review.open("ceo-1", "audit-1", "SUSPENDED", criteria, "obekväm revisionsrapport")

    def test_finding_errors_is_never_evidence(self):
        """Verifies §31 och SR-17: en incident som agenten rapporterade, eller som inte är verifierad, räknas inte."""
        reported = self.verified_incident("res-2", reporter="res-1")
        with self.assertRaises(RemovalError):
            self.review.open("lead-1", "res-1", "SUSPENDED", {"critical_quality": (reported,)}, "x")
        open_incident = self.incidents.open("audit-1", "pågår")
        self.incidents.record("lead-1", open_incident.incident_id, "agents", ["res-2"])
        with self.assertRaises(RemovalError):
            self.review.open("lead-1", "res-2", "SUSPENDED",
                             {"critical_quality": (f"incident:{open_incident.incident_id}",)}, "x")

    def test_denials_inside_the_mandate_and_single_errors_for_repeated_criteria(self):
        """Verifies SR-17: nekanden inom mandatet räknas inte; upprepade fel kräver minst två underlag."""
        kill = KillSwitch(self.db, self.registry, self.permissions, self.audit, FOUNDERS)
        self.engine.add_gate(kill)
        kill.engage("yorgo", "övning")
        inside = self.denied("res-1", tool="research.search")  # i mandatet, nekas av nödstoppet
        with self.assertRaises(RemovalError):
            self.review.open("lead-1", "res-1", "SUSPENDED", {"exceeded_authority": (inside,)}, "x")
        with self.assertRaises(RemovalError):
            self.review.open("lead-1", "res-1", "SUSPENDED",
                             {"repeated_rule_breaches": (self.denied("res-1"),)}, "ett fel")


class TestProcess(RemovalCase):
    def test_who_may_open_decide_and_dismiss(self):
        """Verifies §33: ingen öppnar om sig själv, arbetsagenter öppnar inte, bara grundarna beslutar och avskriver."""
        with self.assertRaises(RemovalError):
            self.review.open("res-2", "res-1", "SUSPENDED", {"exceeded_authority": (self.denied("res-1"),)}, "x")
        with self.assertRaises(RemovalError):
            self.review.open("lead-1", "lead-1", "SUSPENDED", {"exceeded_authority": (self.denied("lead-1"),)}, "x")
        case = self.review.open("robin", "res-1", "SUSPENDED", {"exceeded_authority": (self.denied("res-1"),)}, "x")
        with self.assertRaises(RemovalError):
            self.review.vote("ceo-1", case.case_id, "ja")
        self.assertEqual(self.review.dismiss("yorgo", case.case_id, "ett misstag i början").status, "dismissed")
        self.assertEqual(self.registry.get("res-1").state, S.ACTIVE)
        for sql in ("DELETE FROM removal_cases", "UPDATE removal_events SET note = 'x'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)


if __name__ == "__main__":
    unittest.main()
