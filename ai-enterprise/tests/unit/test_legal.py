"""Tester för juridisk konflikt (Fas 3h). Verifierar SR-16, FR-03 och §6."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.collaboration import ConsultationBoard, Position
from aie.config import Money
from aie.memory import Database
from aie.orchestration import LegalDesk, LegalError, TaskBoard, TaskError, TaskStatus

ROOT = Path(__file__).resolve().parents[2]
S, P, T = AgentState, Position, TaskStatus
FOUNDERS = frozenset({"yorgo", "robin"})
TERMS = ("url:https://www.etsy.com/legal/creativity",)


class LegalCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.start()
        self.add("ceo-1", "ceo")
        for agent_id, role in (("cro-1", "cro"), ("comp-1", "compliance")):
            self.add(agent_id, role)
        self.add("lead-1", "research_lead", "ceo-1")
        self.add("res-1", "researcher", "lead-1")
        task = self.board.create("ceo-1", "Publicera AI-mallar på Etsy")
        self.task = self.board.assign("lead-1", task.task_id, "res-1")
        self.board.start("res-1", self.task.task_id)

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.board = TaskBoard(self.db, self.registry, engine, FOUNDERS)
        self.consultations = ConsultationBoard(self.db, self.registry, self.permissions, self.audit, FOUNDERS,
                                               Money(10_000, "SIM"))
        self.desk = LegalDesk(self.db, self.board, self.consultations, self.registry, self.audit, FOUNDERS)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def flag(self, actor="res-1"):
        return self.desk.raise_conflict(actor, self.task.task_id, "Etsy kräver att AI-användning anges", TERMS)


class TestRaise(LegalCase):
    def test_worker_flag_stops_task_and_opens_compliance_consultation(self):
        """Verifies SR-16: en arbetsagent flaggar; uppgiften blockeras och Compliance och CRO måste yttra sig."""
        hold = self.flag()
        self.assertEqual(self.board.get(self.task.task_id).status, T.BLOCKED)
        consultation = self.consultations.get(hold.consultation_id)
        self.assertEqual(consultation.required_roles, ("cro", "compliance"))
        self.assertEqual(consultation.subject, f"task:{self.task.task_id}")
        self.assertIn("legal.conflict_raised", [e.action for e in self.audit.entries()])

    def test_held_task_cannot_continue_by_any_route(self):
        """Verifies SR-16: varken ägaren, chefen eller en grundare kan starta, tilldela om eller slutföra uppgiften."""
        self.flag()
        tid = self.task.task_id
        for call in (lambda: self.board.start("res-1", tid),
                     lambda: self.board.start("yorgo", tid),
                     lambda: self.board.assign("lead-1", tid, "ceo-1"),
                     lambda: self.board.complete("res-1", tid, "klart ändå")):
            with self.assertRaises(TaskError) as ctx:
                call()
            self.assertIn("SR-16", str(ctx.exception))

    def test_needs_description_evidence_and_open_task(self):
        """Verifies SR-16: flaggningen kräver beskrivning, spårbart underlag och en uppgift som inte är avslutad."""
        tid = self.task.task_id
        for args in (("", TERMS), ("x", ()), ("x", ("lita på mig",))):
            with self.subTest(args=args), self.assertRaises(LegalError):
                self.desk.raise_conflict("res-1", tid, *args)
        self.flag()
        with self.assertRaises(LegalError):
            self.flag()  # redan hållen

    def test_suspended_agent_cannot_flag(self):
        """Verifies SR-16: bara agenter som får agera, eller grundare, kan flagga."""
        self.registry.transition("res-1", S.SUSPENDED, "yorgo", "test")
        with self.assertRaises(LegalError):
            self.flag("res-1")
        self.assertIsNotNone(self.flag("robin"))


class TestRelease(LegalCase):
    def setUp(self):
        super().setUp()
        self.hold = self.flag()

    def answer(self, compliance=P.SUPPORT, evidence=()):
        cid = self.hold.consultation_id
        self.consultations.respond("cro-1", cid, P.SUPPORT, "låg risk om AI anges")
        self.consultations.respond("comp-1", cid, compliance, "villkoren genomgångna", evidence)

    def test_only_compliance_or_founder_releases(self):
        """Verifies SR-16: varken CEO, chefen, CRO eller agenten själv kan släppa en juridisk hållning."""
        self.answer()
        for actor in ("ceo-1", "lead-1", "cro-1", "res-1"):
            with self.subTest(actor=actor), self.assertRaises(LegalError):
                self.desk.release(actor, self.hold.hold_id, "cleared", "OK")

    def test_cannot_clear_before_consultation_is_complete(self):
        """Verifies SR-16: hållningen kan inte släppas innan Compliance och CRO har yttrat sig."""
        with self.assertRaises(LegalError) as ctx:
            self.desk.release("comp-1", self.hold.hold_id, "cleared", "OK")
        self.assertIn("väntar på", str(ctx.exception))

    def test_compliance_objection_cannot_be_overridden(self):
        """Verifies §6 och SR-16: inte ens en grundare kan släppa förbi en invändning från Compliance."""
        self.answer(P.OBJECT, ("url:https://www.etsy.com/legal/prohibited",))
        for actor in ("comp-1", "yorgo"):
            with self.subTest(actor=actor), self.assertRaises(LegalError):
                self.desk.release(actor, self.hold.hold_id, "cleared", "vi tar risken")
        task = self.desk.release("comp-1", self.hold.hold_id, "cancelled", "förbjuden varutyp")
        self.assertEqual(task.status, T.CANCELLED)

    def test_cleared_task_continues(self):
        """Verifies SR-16: när Compliance stödjer kan uppgiften fortsätta hos sin ägare."""
        self.answer()
        task = self.desk.release("comp-1", self.hold.hold_id, "cleared", "AI anges i annonsen")
        self.assertEqual((task.status, task.owner_id), (T.ASSIGNED, "res-1"))
        self.assertEqual(self.board.start("res-1", task.task_id).status, T.IN_PROGRESS)
        events = [e.event for e in self.board.events(task.task_id)]
        self.assertIn("legal_hold", events)
        self.assertIn("legal_cleared", events)
        with self.assertRaises(LegalError):
            self.desk.release("comp-1", self.hold.hold_id, "cleared", "igen")

    def test_hold_survives_restart_and_database_protects_it(self):
        """Verifies FR-03 och SR-16: hållningen gäller efter omstart och kan inte raderas eller ändras."""
        self.db.close()
        self.start()
        with self.assertRaises(TaskError):
            self.board.start("res-1", self.task.task_id)
        for sql in ("DELETE FROM legal_holds", "UPDATE legal_holds SET description = 'inget'",
                    "UPDATE legal_holds SET outcome = 'cleared'"):  # halvt släppt
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)


if __name__ == "__main__":
    unittest.main()
