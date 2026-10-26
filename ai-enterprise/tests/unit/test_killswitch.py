"""Tester för nödstoppet (Fas 4e-2). Verifierar SR-07, §38, D-030 och FR-03."""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, load_budgets
from aie.config import load_config
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.orchestration import TaskBoard
from aie.risk import KillSwitch, KillSwitchError

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})


class KillCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.departments = {m.department for m in self.permissions.roles.values()}
        self.limits = load_config(ROOT / "config").risk
        self.budgets = load_budgets(ROOT / "config", self.departments, self.limits)
        self.start()
        self.add("ceo-1", "ceo")
        for agent_id, role in (("cro-1", "cro"), ("audit-1", "auditor")):
            self.add(agent_id, role)
        self.add("lead-1", "research_lead", "ceo-1")
        self.ledger.record("robin", EntryDraft("start", "finance", 1_000_000, "SIM", EntryType.CAPITAL_IN, "start",
                                               Approval.APPROVED, ("decision:start",), status=Status.SETTLED))

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.switch = KillSwitch(self.db, self.registry, self.permissions, self.audit, FOUNDERS,
                                 components=frozenset({"system:protected-mode"}))
        self.engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit, gates=(self.switch,))
        self.ledger = Ledger(self.db, self.engine, self.departments, FOUNDERS, self.audit, approval_threshold=10_000)
        self.budget = BudgetEngine(self.ledger, self.limits, self.budgets, self.audit, gates=(self.switch,))
        self.board = TaskBoard(self.db, self.registry, self.engine, FOUNDERS)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def spend_allowed(self):
        return self.budget.check("x", SpendRequest("research", 1_000, "SIM", "etsy", Risk.LOW)).allowed


class TestEngage(KillCase):
    def test_engaged_blocks_spending_external_actions_and_new_tasks(self):
        """Verifies SR-07 (§38): inga nya transaktioner, inga modellanrop eller webbsökningar, inga nya uppgifter."""
        self.assertTrue(self.spend_allowed())
        self.switch.engage("cro-1", "okända transaktioner i ledgern")
        self.assertFalse(self.spend_allowed())
        for agent_id, tool in (("lead-1", "llm.complete"), ("lead-1", "research.search"), ("ceo-1", "task.create")):
            with self.subTest(tool=tool):
                decision = self.engine.check(agent_id, tool)
                self.assertFalse(decision.allowed)
                self.assertIn("SR-07", decision.reason)
        with self.assertRaises(PermissionDenied):
            self.board.create("ceo-1", "ny uppgift under nödstopp")

    def test_analysis_and_documentation_still_work(self):
        """Verifies SR-07: läsa, rapportera, verifiera och stoppa fungerar fortfarande, så att läget kan utredas."""
        self.switch.engage("yorgo", "test")
        for agent_id, tool in (("audit-1", "audit.verify"), ("audit-1", "ledger.read"),
                               ("lead-1", "report.write"), ("cro-1", "risk.assess"), ("cro-1", "action.block")):
            with self.subTest(tool=tool):
                self.assertTrue(self.engine.check(agent_id, tool).allowed)

    def test_nothing_is_deleted_and_facts_are_still_recorded(self):
        """Verifies SR-07 (§38): nödstoppet raderar inget, och ledgern tar fortfarande emot fakta."""
        before = self.db.connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        audit_before = len(list(self.audit.entries()))
        self.switch.engage("yorgo", "test")
        self.ledger.record("robin", EntryDraft("faktura", "research", 500, "SIM", EntryType.COST, "etsy",
                                               Approval.NOT_REQUIRED, ("file:faktura.pdf",), status=Status.SETTLED))
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0], before + 1)
        self.assertGreater(len(list(self.audit.entries())), audit_before)
        self.assertTrue(self.audit.verify().ok)

    def test_who_can_engage(self):
        """Verifies SR-07: grundare, kontrollfunktioner och angivna systemkomponenter, men inte CEO eller chefer."""
        for actor in ("ceo-1", "lead-1", "system:okand"):
            with self.subTest(actor=actor), self.assertRaises(KillSwitchError):
                self.switch.engage(actor, "x")
        self.assertTrue(self.switch.engage("system:protected-mode", "skyddat läge eskalerar").engaged)
        with self.assertRaises(KillSwitchError):
            self.switch.engage("yorgo", " ")

    def test_engage_is_logged_with_who_to_inform(self):
        """Verifies SR-07 (§38): aktiveringen loggas och anger vilka som ska informeras."""
        self.switch.engage("audit-1", "siffrorna stämmer inte")
        entry = next(e for e in self.audit.entries() if e.action == "kill.engaged")
        self.assertEqual(entry.details["notify"], ["founders", "role:cro", "role:auditor"])
        self.assertEqual(len([e for e in self.audit.entries() if e.action == "kill.engaged"]), 1)
        self.switch.engage("yorgo", "igen")  # redan aktivt: ingen ny händelse
        self.assertEqual(len([e for e in self.audit.entries() if e.action == "kill.engaged"]), 1)


class TestRelease(KillCase):
    def setUp(self):
        super().setUp()
        self.switch.engage("cro-1", "okända transaktioner")

    def test_restart_needs_two_different_founders(self):
        """Verifies SR-07 och D-030: en grundare räcker inte; samma grundare två gånger räcker inte."""
        for actor in ("cro-1", "ceo-1"):
            with self.subTest(actor=actor), self.assertRaises(KillSwitchError):
                self.switch.vote_release(actor, "OK")
        state = self.switch.vote_release("yorgo", "utrett: felaktig import")
        self.assertTrue(state.engaged)
        self.assertFalse(self.spend_allowed())
        with self.assertRaises(KillSwitchError):
            self.switch.vote_release("yorgo", "igen")
        state = self.switch.vote_release("robin", "instämmer")
        self.assertFalse(state.engaged)
        self.assertTrue(self.spend_allowed())
        self.assertTrue(self.engine.check("lead-1", "llm.complete").allowed)

    def test_no_restart_while_audit_log_is_broken(self):
        """Verifies SR-07 och §59: med en manipulerad revisionslogg går det inte att starta om."""
        execute = self.db.connection.execute
        execute("DROP TRIGGER audit_log_no_update")
        execute("UPDATE audit_log SET action = 'förfalskad' WHERE seq = 1")
        with self.assertRaises(KillSwitchError) as ctx:
            self.switch.vote_release("yorgo", "allt OK")
        self.assertIn("revisionsloggen är trasig", str(ctx.exception))
        self.assertTrue(self.switch.state().engaged)

    def test_votes_reset_on_new_engage(self):
        """Verifies D-030: röster från en tidigare återstart räknas inte för nästa nödstopp."""
        self.switch.vote_release("yorgo", "a")
        self.switch.vote_release("robin", "b")
        self.switch.engage("cro-1", "nytt problem")
        self.assertEqual(self.switch.state().release_votes, ())

    def test_survives_restart_and_is_append_only(self):
        """Verifies FR-03 och SR-07: nödstoppet gäller efter omstart, och händelserna kan inte ändras."""
        self.db.close()
        self.start()
        self.assertTrue(self.switch.state().engaged)
        self.assertFalse(self.spend_allowed())
        for sql in ("DELETE FROM kill_switch_events", "UPDATE kill_switch_events SET event = 'released'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)


class TestCli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        shutil.copytree(ROOT / "config", self.dir / "config")

    def aie(self, *args):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        return subprocess.run([sys.executable, "-m", "aie", *args], cwd=self.dir, env=env,
                              capture_output=True, encoding="utf-8", timeout=60, check=False)

    def test_cli_engage_status_and_two_founder_release(self):
        """Verifies SR-07 och D-030: `python -m aie kill` aktiverar, visar och släpper enligt processen."""
        founders = load_config(self.dir / "config").system.founders
        self.assertEqual(self.aie("init").returncode, 0)
        self.assertIn("av", self.aie("kill", "status").stdout)
        self.assertEqual(self.aie("kill", "engage").returncode, 1)  # --as och --reason krävs
        self.assertEqual(self.aie("kill", "engage", "--as", "mallory", "--reason", "x").returncode, 1)
        result = self.aie("kill", "engage", "--as", founders[0], "--reason", "test av nödstopp")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AKTIVT", self.aie("kill", "status").stdout)
        self.aie("kill", "release", "--as", founders[0], "--reason", "utrett")
        self.assertEqual(self.aie("kill", "release", "--as", founders[0], "--reason", "igen").returncode, 1)
        done = self.aie("kill", "release", "--as", founders[1], "--reason", "instämmer")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("av", self.aie("kill", "status").stdout)
        with closing(sqlite3.connect(self.dir / "data" / "sim.db")) as conn:
            events = [r[0] for r in conn.execute("SELECT event FROM kill_switch_events ORDER BY id")]
        self.assertEqual(events, ["engaged", "release_vote", "release_vote", "released"])


if __name__ == "__main__":
    unittest.main()
