"""Tester för incidentrapporter (Fas 5a). Verifierar FR-15, §28, §31, §33 och FR-03."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import load_budgets
from aie.config import load_config
from aie.evaluation import FIELDS, IncidentError, IncidentLog
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.risk import KillSwitch, ProtectedMode, StopLoss

from .fixture_config import TEST_CONFIG

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})
FULL = {
    "department": "research",
    "agents": ["res-2"],
    "goal": "sälja 10 mallar på Etsy",
    "forecast": "10 sålda, netto 4 000 SIM",
    "actions": "annonser publicerade utan AI-märkning",
    "outcome": "annonserna togs bort av Etsy",
    "economic_impact": {"amount_minor": -1_200, "currency": "SIM"},
    "deviation": "0 sålda i stället för 10",
    "root_cause": "AI-märkningen saknades",
    "contributing": "checklistan för Etsy fanns inte",
    "corrective": "märkningen tillagd, annonserna publicerade igen",
    "preventive": "kontroll av AI-märkning före publicering",
    "follow_up_owner": "comp-1",
}


class IncidentCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(TEST_CONFIG)
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
        self.log = IncidentLog(self.db, self.registry, self.permissions, self.audit, FOUNDERS)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def filled(self, reporter="res-1"):
        incident = self.log.open(reporter, "Etsy tog bort våra annonser")
        for key, value in FULL.items():
            incident = self.log.record("lead-1", incident.incident_id, key, value)
        return incident


class TestFields(IncidentCase):
    def test_all_sixteen_fields_of_section_28(self):
        """Verifies FR-15: incidenten har exakt de 16 fälten i §28, i den ordningen."""
        self.assertEqual([label for _, label in FIELDS], [
            "Incident-ID", "Datum", "Ansvarigt departement", "Involverade agenter", "Ursprungligt mål",
            "Ursprunglig prognos", "Genomförda åtgärder", "Faktiskt utfall", "Ekonomisk påverkan",
            "Avvikelse från prognosen", "Identifierad grundorsak", "Bidragande faktorer", "Korrigerande åtgärd",
            "Föreslagen förebyggande åtgärd", "Ansvarig för uppföljning", "Resultat av efterföljande verifiering",
        ])

    def test_complete_report_after_all_fields_and_independent_verification(self):
        """Verifies FR-15: när alla fält och en oberoende verifiering finns är rapporten komplett."""
        incident = self.filled()
        self.assertEqual(incident.missing, ("verification",))
        self.assertIn(incident, self.log.open_incidents())
        incident = self.log.record("audit-1", incident.incident_id, "verification", "nya annonser kvar efter 14 dagar")
        self.assertTrue(incident.complete)
        report = dict(incident.as_report())
        self.assertEqual(report["Incident-ID"], incident.incident_id)
        self.assertEqual(report["Ekonomisk påverkan"], {"amount_minor": -1_200, "currency": "SIM"})
        self.assertNotIn(incident, self.log.open_incidents())

    def test_verification_last_and_not_by_follow_up_owner(self):
        """Verifies FR-15 (§28): verifieringen görs sist och inte av den som ansvarar för uppföljningen."""
        incident = self.log.open("res-1", "x")
        with self.assertRaises(IncidentError):
            self.log.record("audit-1", incident.incident_id, "verification", "OK")
        incident = self.filled()
        with self.assertRaises(IncidentError):
            self.log.record("comp-1", incident.incident_id, "verification", "jag verifierar mig själv")

    def test_values_are_validated(self):
        """Verifies FR-15: fel format, okända agenter, okända fält och automatiska fält avvisas."""
        incident = self.log.open("res-1", "x")
        for field, value in (("economic_impact", 12.5), ("economic_impact", {"amount_minor": 1}),
                             ("agents", ["ghost"]), ("agents", []), ("magic", "x"), ("incident_id", "9"),
                             ("date", "2020-01-01"), ("goal", " ")):
            with self.subTest(field=field), self.assertRaises(IncidentError):
                self.log.record("lead-1", incident.incident_id, field, value)


class TestNeverRewritten(IncidentCase):
    def test_correction_is_a_new_entry_with_reason(self):
        """Verifies FR-15: ett ifyllt fält skrivs aldrig om; en rättelse är en ny post med motivering."""
        incident = self.log.open("res-1", "x")
        first = self.log.record("lead-1", incident.incident_id, "root_cause", "fel pris")
        with self.assertRaises(IncidentError):
            self.log.record("lead-1", incident.incident_id, "root_cause", "fel bild")
        corrected = self.log.record("cro-1", incident.incident_id, "root_cause", "fel bild", "bilden bröt mot villkoren")
        self.assertEqual(corrected.fields["root_cause"], "fel bild")
        old, new = [e for e in corrected.history if e.field == "root_cause"]
        self.assertEqual((old.value, new.corrects, new.note), ("fel pris", old.entry_id, "bilden bröt mot villkoren"))
        self.assertEqual(first.history[0].entry_id, old.entry_id)

    def test_database_blocks_edit_and_delete(self):
        """Verifies FR-15: incidenter och poster kan inte ändras eller raderas, inte ens med SQL."""
        incident = self.filled()
        for sql in ("UPDATE incidents SET title = 'inget hände'", "DELETE FROM incidents",
                    "UPDATE incident_entries SET value = '{}'", "DELETE FROM incident_entries"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)
        self.db.close()
        self.start()
        self.assertEqual(self.log.get(incident.incident_id).fields["goal"], FULL["goal"])  # FR-03


class TestWhoAndFairness(IncidentCase):
    def test_anyone_acting_can_report_but_only_some_can_write(self):
        """Verifies FR-15: alla aktiva agenter kan öppna en incident; andra arbetsagenter kan inte skriva i den."""
        incident = self.log.open("res-1", "möjligt fel i prisräkningen")
        self.log.record("res-1", incident.incident_id, "outcome", "priset blev för lågt")  # rapportören får
        with self.assertRaises(IncidentError):
            self.log.record("res-2", incident.incident_id, "root_cause", "res-1 slarvade")
        self.registry.transition("res-2", S.SUSPENDED, "yorgo", "test")
        with self.assertRaises(IncidentError):
            self.log.open("res-2", "x")

    def test_finding_an_error_is_not_counted_against_the_finder(self):
        """Verifies §31 och §33: den som hittar felet räknas inte som involverad, bara som rapportör."""
        incident = self.filled(reporter="res-1")
        self.assertEqual(incident.reported_by, "res-1")
        self.assertNotIn("res-1", incident.involved)
        self.assertEqual(self.log.involving("res-1"), ())
        self.assertEqual([i.incident_id for i in self.log.reported_by("res-1")], [incident.incident_id])
        self.assertEqual([i.incident_id for i in self.log.involving("res-2")], [incident.incident_id])


class TestFromStops(IncidentCase):
    def setUp(self):
        super().setUp()
        departments = {m.department for m in self.permissions.roles.values()}
        self.limits = load_config(TEST_CONFIG).risk
        engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.ledger = Ledger(self.db, engine, departments, FOUNDERS, self.audit, approval_threshold=10_000)
        self.ledger.record("robin", EntryDraft("start", "finance", 1_000_000, "SIM", EntryType.CAPITAL_IN, "start",
                                               Approval.APPROVED, ("decision:start",), status=Status.SETTLED))
        self.budgets = load_budgets(TEST_CONFIG, departments, self.limits)
        self.engine = engine

    def test_stop_loss_trip_creates_prefilled_incident(self):
        """Verifies FR-15 och ER-13: en stop-loss-utlösning blir automatiskt en incident med förifyllda fält."""
        stoploss = StopLoss(self.db, self.ledger, self.limits, self.budgets, self.audit, FOUNDERS, incidents=self.log)
        self.ledger.record("robin", EntryDraft("k1", "research", 50_000, "SIM", EntryType.COST, "stor-order",
                                               Approval.UNAPPROVED, ("decision:x",), status=Status.PENDING))
        (trip,) = stoploss.evaluate()
        (incident,) = self.log.all()
        self.assertEqual((incident.source, incident.reported_by), (f"stoploss:{trip.trip_id}", "system:incidents"))
        fields = incident.fields
        self.assertEqual(fields["department"], "research")
        self.assertEqual(fields["economic_impact"], {"amount_minor": 50_000, "currency": "SIM"})
        self.assertEqual(fields["follow_up_owner"], "role:cro")
        self.assertIn("ER-13", fields["actions"])

    def test_kill_switch_and_protected_mode_create_incidents(self):
        """Verifies FR-15, SR-07 och SR-08: nödstopp och skyddat driftläge blir automatiskt incidenter."""
        kill = KillSwitch(self.db, self.registry, self.permissions, self.audit, FOUNDERS, incidents=self.log)
        kill.engage("cro-1", "okända transaktioner")
        mode = ProtectedMode(self.db, self.ledger, self.registry, self.permissions, self.limits, self.engine,
                             self.audit, FOUNDERS, incidents=self.log)
        mode.report_incident("audit-1", "misstänkt intrång")
        sources = [i.source.split(":")[0] for i in self.log.all()]
        self.assertEqual(sources, ["kill", "mode"])
        self.assertIn("okända transaktioner", self.log.all()[0].fields["actions"])

    def test_sync_catches_stops_without_hook_and_is_idempotent(self):
        """Verifies FR-15: sync() hittar stopp som skett utan koppling och skapar aldrig dubbletter."""
        KillSwitch(self.db, self.registry, self.permissions, self.audit, FOUNDERS).engage("yorgo", "övning")
        self.assertEqual(self.log.all(), ())
        self.assertEqual(len(self.log.sync()), 1)
        self.assertEqual(self.log.sync(), ())
        self.assertEqual(len(self.log.all()), 1)


if __name__ == "__main__":
    unittest.main()
