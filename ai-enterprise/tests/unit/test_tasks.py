"""Tester för src/aie/orchestration/tasks.py (Fas 2). Verifierar FR-07, SR-01 och SR-02."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.memory import Database
from aie.orchestration import TaskBoard, TaskError, TaskStatus

from .org_helpers import register_in_line

ROOT = Path(__file__).resolve().parents[2]
S, T = AgentState, TaskStatus


class TaskCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.open_db()
        self.permissions = load_permissions(ROOT / "config")  # de riktiga mandaten
        self.registry = AgentRegistry(self.permissions, self.db)
        self.audit = AuditLog(self.db)
        engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.board = TaskBoard(self.db, self.registry, engine, founders=frozenset({"yorgo", "robin"}))
        # En riktig befälskedja: uppgifter tilldelas bara nedåt i den (§8, D-023).
        for agent_id, role, manager in (
            ("ceo-1", "ceo", None),
            ("lead-1", "research_lead", "ceo-1"),
            ("res-1", "researcher", "lead-1"),
            ("res-2", "researcher", "lead-1"),
        ):
            self.activate(agent_id, role, manager)

    def open_db(self):
        db = Database.open(self.dir / "data", "sim")
        self.addCleanup(db.close)
        return db

    def activate(self, agent_id, role, manager=...):
        if manager is ...:
            register_in_line(self.registry, self.permissions, agent_id, role)
        else:
            self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def assigned_task(self, owner="res-1"):
        task = self.board.create("ceo-1", "Utred Gumroad-avgifter", "R-02")
        return self.board.assign("ceo-1", task.task_id, owner)


class TestLifecycle(TaskCase):
    def test_full_flow_create_assign_start_complete(self):
        """Verifies FR-07: en uppgift skapas, tilldelas, utförs och avslutas med ägare och status."""
        task = self.assigned_task()
        self.board.start("res-1", task.task_id)
        done = self.board.complete("res-1", task.task_id, "rapport R-02 skriven")
        self.assertEqual((done.status, done.owner_id), (T.DONE, "res-1"))
        events = [(e.event, e.new_status) for e in self.board.events(task.task_id)]
        self.assertEqual(events, [
            ("created", T.OPEN), ("assigned", T.ASSIGNED), ("started", T.IN_PROGRESS), ("completed", T.DONE),
        ])

    def test_block_and_resume(self):
        """Verifies FR-07: en blockerad uppgift kan återupptas av ägaren och har en motivering."""
        task = self.assigned_task()
        self.board.start("res-1", task.task_id)
        with self.assertRaises(TaskError):
            self.board.block("res-1", task.task_id, "")
        self.board.block("res-1", task.task_id, "väntar på CFO")
        self.assertEqual(self.board.start("res-1", task.task_id).status, T.IN_PROGRESS)

    def test_reassign_records_new_owner(self):
        """Verifies FR-07: ny ägare registreras som en egen händelse."""
        task = self.assigned_task()
        self.board.assign("lead-1", task.task_id, "res-2", "res-1 är upptagen")
        self.assertEqual(self.board.get(task.task_id).owner_id, "res-2")
        self.assertEqual(self.board.events(task.task_id)[-1].event, "reassigned")

    def test_finished_task_is_final(self):
        """Verifies FR-07: en avslutad eller avbruten uppgift kan inte ändras, varken via kod eller SQL."""
        task = self.assigned_task()
        self.board.cancel("ceo-1", task.task_id, "behövs inte")
        with self.assertRaises(TaskError):
            self.board.start("res-1", task.task_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute("UPDATE tasks SET status = 'open' WHERE task_id = ?", (task.task_id,))

    def test_complete_requires_in_progress_and_note(self):
        """Verifies FR-07 (§7): bara påbörjat arbete kan slutföras, och med en beskrivning."""
        task = self.assigned_task()
        with self.assertRaises(TaskError):
            self.board.complete("res-1", task.task_id, "klart")  # aldrig startad
        self.board.start("res-1", task.task_id)
        with self.assertRaises(TaskError):
            self.board.complete("res-1", task.task_id, " ")

    def test_tasks_survive_restart_and_filter(self):
        """Verifies FR-03 och FR-07: uppgifter och historik finns kvar efter omstart."""
        task = self.assigned_task()
        self.board.create("yorgo", "Annan uppgift")
        self.db.close()
        db = self.open_db()
        registry = AgentRegistry(self.permissions, db)
        board = TaskBoard(db, registry, AuthorizationEngine(self.permissions, registry, "sim"), frozenset({"yorgo"}))
        self.assertEqual([t.task_id for t in board.tasks(owner_id="res-1")], [task.task_id])
        self.assertEqual(len(board.tasks(status=T.OPEN)), 1)
        self.assertEqual(len(board.events(task.task_id)), 2)


class TestPermissions(TaskCase):
    def test_create_requires_task_create(self):
        """Verifies SR-02: en researcher saknar task.create och nekas; försöket loggas."""
        with self.assertRaises(PermissionDenied):
            self.board.create("res-1", "Egen idé")
        self.assertEqual(list(self.audit.entries())[-1].action, "tool.denied")
        self.assertEqual(self.board.tasks(), ())

    def test_founder_can_create_without_agent_mandate(self):
        """Verifies FR-07: grundarna (nivå 0) kan skapa och tilldela uppgifter."""
        task = self.board.create("robin", "Grundaruppgift")
        self.assertEqual(self.board.assign("robin", task.task_id, "res-1").owner_id, "res-1")

    def test_assign_requires_task_assign_and_valid_owner(self):
        """Verifies SR-02: tilldelning kräver task.assign och en ägare som får agera."""
        task = self.board.create("ceo-1", "x")
        with self.assertRaises(PermissionDenied):
            self.board.assign("res-1", task.task_id, "res-2")
        self.registry.transition("res-2", S.SUSPENDED, "yorgo", "test")
        for owner in ("res-2", "ghost"):
            with self.subTest(owner=owner), self.assertRaises(TaskError):
                self.board.assign("ceo-1", task.task_id, owner)

    def test_cannot_assign_to_self(self):
        """Verifies SR-03: en agent kan inte ge sig själv en uppgift."""
        task = self.board.create("ceo-1", "x")
        with self.assertRaises(TaskError):
            self.board.assign("ceo-1", task.task_id, "ceo-1")

    def test_only_owner_works_on_task(self):
        """Verifies SR-01: bara ägaren kan starta, blockera och slutföra."""
        task = self.assigned_task(owner="res-1")
        with self.assertRaises(TaskError):
            self.board.start("res-2", task.task_id)
        self.assertEqual(self.board.get(task.task_id).status, T.ASSIGNED)

    def test_cancel_rules(self):
        """Verifies SR-01: bara skaparen, en agent med task.assign eller en grundare får avbryta."""
        task = self.assigned_task()
        with self.assertRaises(TaskError):
            self.board.cancel("res-1", task.task_id, "vill inte")
        self.assertEqual(self.board.cancel("lead-1", task.task_id, "prioriteras bort").status, T.CANCELLED)

    def test_database_blocks_delete_and_owner_rule(self):
        """Verifies FR-07: uppgifter raderas aldrig, och en tilldelad uppgift måste ha ägare."""
        task = self.assigned_task()
        for sql in (
            f"DELETE FROM tasks WHERE task_id = {task.task_id}",
            f"UPDATE tasks SET owner_id = NULL WHERE task_id = {task.task_id}",
            "DELETE FROM task_events",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)


if __name__ == "__main__":
    unittest.main()
