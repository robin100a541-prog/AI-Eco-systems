"""Tester för kontrollfunktionernas stopp (Fas 3b). Verifierar SR-05 och FR-03."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import (
    AuthorizationEngine,
    ControlStops,
    PermissionDenied,
    StopError,
    load_permissions,
)
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"yorgo", "robin"})


class StopCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
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
        self.stops = ControlStops(self.db, self.registry, self.permissions, self.audit, FOUNDERS)
        self.engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit, stops=self.stops)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")


class TestPlacing(StopCase):
    def test_control_function_stops_agent_and_engine_denies(self):
        """Verifies SR-05: CRO stoppar en agent; agenten nekas alla verktyg och skälet syns och loggas."""
        stop = self.stops.place("cro-1", "agent", "res-1", "osäker källa i senaste rapporten")
        with self.assertRaises(PermissionDenied) as ctx:
            self.engine.require("res-1", "report.write")
        self.assertIn(f"stopp #{stop.stop_id}", str(ctx.exception))
        self.assertIn("SR-05", str(ctx.exception))
        self.assertTrue(self.engine.check("res-2", "report.write").allowed)  # bara den stoppade agenten
        entries = list(self.audit.entries())
        self.assertIn("stop.placed", [e.action for e in entries])
        denied = [e for e in entries if e.action == "tool.denied"]
        self.assertEqual(denied[-1].details["agent_id"], "res-1")
        self.assertIn("SR-05", denied[-1].details["reason"])

    def test_department_and_tool_stops(self):
        """Verifies SR-05: ett stopp kan gälla ett helt departement eller ett verktyg för alla."""
        self.stops.place("comp-1", "department", "research", "villkoren för källan är oklara")
        self.assertFalse(self.engine.check("lead-1", "report.write").allowed)
        self.assertFalse(self.engine.check("res-2", "report.write").allowed)
        self.assertTrue(self.engine.check("ceo-1", "report.write").allowed)
        self.stops.place("cfo-1", "tool", "task.assign", "för många uppgifter i kö")
        self.assertFalse(self.engine.check("ceo-1", "task.assign").allowed)
        self.assertTrue(self.engine.check("ceo-1", "task.create").allowed)

    def test_ceo_can_be_stopped(self):
        """Verifies SR-05 (§8): CEO är operativ och kan stoppas av en kontrollfunktion."""
        self.stops.place("audit-1", "agent", "ceo-1", "rapporterna stämmer inte med underlaget")
        self.assertFalse(self.engine.check("ceo-1", "task.create").allowed)

    def test_only_control_functions_or_founders_can_place(self):
        """Verifies SR-05: varken CEO, en chef eller en arbetsagent kan sätta stopp."""
        for actor in ("ceo-1", "lead-1", "res-2"):
            with self.subTest(actor=actor), self.assertRaises(StopError):
                self.stops.place(actor, "agent", "res-1", "vill")
        self.assertEqual(self.stops.active(), ())

    def test_control_functions_cannot_stop_each_other(self):
        """Verifies SR-05 (§18): den som granskas kan inte stänga av sin granskare. Bara grundarna kan."""
        for scope, value in (("agent", "audit-1"), ("agent", "cfo-1"), ("department", "audit"), ("tool", "action.block")):
            with self.subTest(scope=scope, value=value), self.assertRaises(StopError):
                self.stops.place("cro-1", scope, value, "x")
        self.stops.place("yorgo", "agent", "audit-1", "grundarna granskar Audit")
        self.assertFalse(self.engine.check("audit-1", "audit.verify").allowed)

    def test_suspended_control_function_cannot_place(self):
        """Verifies SR-05: en avstängd kontrollfunktion har ingen stoppmakt."""
        self.registry.transition("cro-1", S.SUSPENDED, "yorgo", "test")
        with self.assertRaises(StopError):
            self.stops.place("cro-1", "agent", "res-1", "x")

    def test_unknown_targets_and_empty_reason(self):
        """Verifies SR-05: stopp mot något som inte finns, eller utan motivering, avvisas."""
        for args in (("agent", "ghost", "x"), ("department", "magic", "x"), ("tool", "money.send", "x"),
                     ("planet", "x", "x"), ("agent", "res-1", " ")):
            with self.subTest(args=args), self.assertRaises(StopError):
                self.stops.place("cro-1", *args)


class TestLifting(StopCase):
    def setUp(self):
        super().setUp()
        self.stop = self.stops.place("cro-1", "agent", "res-1", "osäker källa")

    def test_no_operational_chief_can_lift(self):
        """Verifies SR-05: varken CEO, chefen eller agenten själv kan häva stoppet."""
        for actor in ("ceo-1", "lead-1", "res-1"):
            with self.subTest(actor=actor), self.assertRaises(StopError) as ctx:
                self.stops.lift(actor, self.stop.stop_id, "jag tycker det är OK")
            self.assertIn("SR-05", str(ctx.exception))
        self.assertFalse(self.engine.check("res-1", "report.write").allowed)

    def test_other_control_function_cannot_lift(self):
        """Verifies SR-05: en annan kontrollfunktion kan inte häva någon annans stopp."""
        with self.assertRaises(StopError):
            self.stops.lift("cfo-1", self.stop.stop_id, "inte mitt område men ändå")

    def test_placer_or_founder_can_lift_with_reason(self):
        """Verifies SR-05: den som satte stoppet, eller en grundare, kan häva det, och det loggas."""
        with self.assertRaises(StopError):
            self.stops.lift("cro-1", self.stop.stop_id, "")
        lifted = self.stops.lift("cro-1", self.stop.stop_id, "källan verifierad")
        self.assertFalse(lifted.active)
        self.assertTrue(self.engine.check("res-1", "report.write").allowed)
        second = self.stops.place("cro-1", "agent", "res-1", "igen")
        self.stops.lift("robin", second.stop_id, "grundarbeslut")
        self.assertEqual(self.stops.active(), ())
        self.assertEqual([e.action for e in self.audit.entries()].count("stop.lifted"), 2)

    def test_cannot_lift_twice(self):
        """Verifies SR-05: ett hävt stopp kan inte hävas igen eller ändras."""
        self.stops.lift("cro-1", self.stop.stop_id, "klart")
        with self.assertRaises(StopError):
            self.stops.lift("yorgo", self.stop.stop_id, "igen")


class TestPersistence(StopCase):
    def test_stop_survives_restart(self):
        """Verifies FR-03 och SR-05: ett stopp gäller fortfarande efter omstart."""
        self.stops.place("cro-1", "agent", "res-1", "osäker källa")
        self.db.close()
        self.start()
        self.assertFalse(self.engine.check("res-1", "report.write").allowed)

    def test_database_blocks_delete_edit_and_unlift(self):
        """Verifies SR-05: stopp kan inte raderas, ändras eller "avhävas", inte ens med SQL."""
        stop = self.stops.place("cro-1", "agent", "res-1", "osäker källa")
        execute = self.db.connection.execute
        for sql in (
            f"DELETE FROM control_stops WHERE stop_id = {stop.stop_id}",
            f"UPDATE control_stops SET scope_value = 'res-2' WHERE stop_id = {stop.stop_id}",
            f"UPDATE control_stops SET lifted_by = 'x' WHERE stop_id = {stop.stop_id}",  # halvt hävt
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                execute(sql)
        self.stops.lift("cro-1", stop.stop_id, "klart")
        with self.assertRaises(sqlite3.IntegrityError):
            execute(f"UPDATE control_stops SET lifted_at = NULL, lifted_by = NULL, lift_reason = NULL WHERE stop_id = {stop.stop_id}")


if __name__ == "__main__":
    unittest.main()
