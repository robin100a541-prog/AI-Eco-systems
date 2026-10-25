"""Tester för tilldelning nedåt i befälskedjan (Fas 3, §8, §51 "Uppgifter går till rätt ansvarig roll", D-023)."""

import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.memory import Database
from aie.orchestration import TaskBoard, TaskError, TaskStatus

ROOT = Path(__file__).resolve().parents[2]
ORG = (  # grundare → CEO → två Research-chefer → deras forskare; kontrollfunktionerna direkt under grundarna
    ("ceo-1", "ceo", None),
    ("cfo-1", "cfo", None),
    ("cro-1", "cro", None),
    ("comp-1", "compliance", None),
    ("audit-1", "auditor", None),
    ("lead-1", "research_lead", "ceo-1"),
    ("lead-2", "research_lead", "ceo-1"),
    ("res-1", "researcher", "lead-1"),
    ("res-2", "researcher", "lead-1"),
    ("res-3", "researcher", "lead-2"),
)


class DelegationCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(ROOT / "config")
        self.registry = AgentRegistry(permissions, self.db)
        engine = AuthorizationEngine(
            permissions, self.registry, "sim", AuditLog(self.db)
        )
        self.board = TaskBoard(
            self.db, self.registry, engine, founders=frozenset({"robin", "yorgo"})
        )
        for agent_id, role, manager in ORG:
            self.registry.register(agent_id, role, manager, "yorgo", "test")
            for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                self.registry.transition(agent_id, state, "yorgo", "test")

    def new_task(self):
        return self.board.create("robin", "Utred begagnade cyklar").task_id

    def assert_refused(self, actor, owner):
        task_id = self.new_task()
        with self.assertRaisesRegex(TaskError, "befälskedja"):
            self.board.assign(actor, task_id, owner)
        task = self.board.get(task_id)
        self.assertEqual((task.status, task.owner_id), (TaskStatus.OPEN, None))
        self.assertEqual([e.event for e in self.board.events(task_id)], ["created"])


class TestDownTheChain(DelegationCase):
    def test_head_assigns_within_own_team(self):
        """Verifies §8 nivå 3: en departementschef fördelar arbete inom sitt departement."""
        task = self.board.assign("lead-1", self.new_task(), "res-1")
        self.assertEqual(task.owner_id, "res-1")
        self.assertEqual(
            self.board.assign("lead-1", task.task_id, "res-2").owner_id, "res-2"
        )

    def test_ceo_assigns_to_heads_and_their_workers(self):
        """Verifies §8 nivå 1: CEO fördelar uppgifter inom den delegerade befälskedjan."""
        for owner in ("lead-1", "lead-2", "res-1", "res-3"):
            self.assertEqual(
                self.board.assign("ceo-1", self.new_task(), owner).owner_id, owner
            )

    def test_owner_hands_own_task_down(self):
        """Verifies §8: CEO får ett uppdrag av grundarna och lämnar det vidare till en chef, som lämnar det till en forskare."""
        task = self.board.assign("robin", self.new_task(), "ceo-1")
        self.assertEqual(self.board.assign("ceo-1", task.task_id, "lead-1").owner_id, "lead-1")
        self.assertEqual(self.board.assign("lead-1", task.task_id, "res-2").owner_id, "res-2")

    def test_founders_assign_to_anyone(self):
        """Verifies §8 nivå 0: grundarna står över hela kedjan, även kontrollfunktionerna."""
        for owner in ("ceo-1", "cfo-1", "comp-1", "audit-1", "res-3"):
            self.assertEqual(
                self.board.assign("yorgo", self.new_task(), owner).owner_id, owner
            )


class TestOutOfLine(DelegationCase):
    def test_head_cannot_assign_upwards_sideways_or_to_another_team(self):
        """Verifies §51: uppgifter går till rätt ansvarig roll, inte till chefen, en kollega eller ett annat team."""
        for owner in ("ceo-1", "lead-2", "res-3", "cfo-1"):
            with self.subTest(owner=owner):
                self.assert_refused("lead-1", owner)

    def test_ceo_cannot_direct_control_functions(self):
        """Verifies §8 nivå 2, D-020: kontrollfunktionerna är oberoende av CEO och tar inte order från den."""
        for owner in ("cfo-1", "cro-1", "comp-1", "audit-1"):
            with self.subTest(owner=owner):
                self.assert_refused("ceo-1", owner)

    def test_reassignment_follows_the_same_rule(self):
        """Verifies D-023: att byta ägare är också en tilldelning och kräver samma befälskedja."""
        task = self.board.assign("ceo-1", self.new_task(), "res-1")
        with self.assertRaisesRegex(TaskError, "befälskedja"):
            self.board.assign("lead-2", task.task_id, "res-3")
        self.assertEqual(self.board.get(task.task_id).owner_id, "res-1")

    def test_worker_without_mandate_cannot_assign_at_all(self):
        """Verifies SR-01: en arbetsagent saknar `task.assign`; mandatet prövas före befälskedjan."""
        with self.assertRaises(PermissionDenied):
            self.board.assign("res-1", self.new_task(), "res-2")


if __name__ == "__main__":
    unittest.main()
