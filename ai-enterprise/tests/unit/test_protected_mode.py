"""Tester för skyddat driftläge (Fas 4e-3). Verifierar SR-08, §59, D-031 och FR-03.

Repots gränser: START_CAPITAL 1 000 000, MINIMUM_RESERVE 300 000 (marginal 10 % = 30 000).
"""
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, load_budgets
from aie.config import load_config
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.risk import KillSwitch, ProtectedMode, ProtectedModeError

ROOT = Path(__file__).resolve().parents[2]
S, T = AgentState, EntryType
FOUNDERS = frozenset({"robin", "yorgo"})


class ModeCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.departments = {m.department for m in self.permissions.roles.values()}
        self.limits = load_config(ROOT / "config").risk
        self.budgets = load_budgets(ROOT / "config", self.departments, self.limits)
        self.n = 0
        self.start()
        self.add("ceo-1", "ceo")
        for agent_id, role in (("cfo-1", "cfo"), ("cro-1", "cro"), ("comp-1", "compliance"), ("audit-1", "auditor")):
            self.add(agent_id, role)
        self.add("lead-1", "research_lead", "ceo-1")
        self.book(1_000_000, T.CAPITAL_IN, department="finance", approval=Approval.APPROVED)

    def start(self, limits=None, kill=False):
        limits = limits or self.limits
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.kill = KillSwitch(self.db, self.registry, self.permissions, self.audit, FOUNDERS,
                               components=frozenset({"system:protected-mode"})) if kill else None
        self.engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.ledger = Ledger(self.db, self.engine, self.departments, FOUNDERS, self.audit, approval_threshold=10_000)
        self.mode = ProtectedMode(self.db, self.ledger, self.registry, self.permissions, limits, self.engine,
                                  self.audit, FOUNDERS, kill_switch=self.kill)
        gates = (self.mode,) + ((self.kill,) if kill else ())
        for gate in gates:  # samma motor används av läget och av spärren
            self.engine.add_gate(gate)
        self.budget = BudgetEngine(self.ledger, limits, self.budgets, self.audit, gates=gates)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def book(self, amount, kind=T.COST, department="research", approval=Approval.NOT_REQUIRED, status=Status.SETTLED):
        self.n += 1
        return self.ledger.record("robin", EntryDraft(f"k{self.n}", department, amount, "SIM", kind, f"i{self.n}",
                                                      approval, ("decision:test",), status=status))

    def spend_allowed(self):
        return self.budget.check("x", SpendRequest("research", 1_000, "SIM", "etsy", Risk.LOW)).allowed


class TestNormal(ModeCase):
    def test_healthy_system_is_not_protected(self):
        """Verifies SR-08: med reserv, kontrollfunktioner och intakt bokföring finns inget skäl."""
        self.assertEqual(self.mode.assess(), ())
        self.assertTrue(self.spend_allowed())
        self.assertFalse(self.mode.state().protected)


class TestConditions(ModeCase):
    def assert_enters(self, fragment):
        self.assertFalse(self.spend_allowed())  # spärren anropar update() före utgiften
        state = self.mode.state()
        self.assertTrue(state.protected)
        self.assertTrue(any(fragment in r for r in state.reasons), state.reasons)

    def test_reserve_close(self):
        """Verifies SR-08 (§59): disponibelt kapital nära reserven ger skyddat läge."""
        self.book(680_000, T.CAPITAL_OUT, department="finance", approval=Approval.APPROVED)
        self.assert_enters("närmar sig reserven")

    def test_missing_reserve_limit(self):
        """Verifies SR-08 och ER-02: utan MINIMUM_RESERVE kan reserven inte skyddas."""
        self.start(replace(self.limits, minimum_reserve=None))
        self.assert_enters("MINIMUM_RESERVE saknas")

    def test_broken_audit_chain(self):
        """Verifies SR-08 (§59): ekonomisk redovisning som inte går att verifiera ger skyddat läge."""
        self.db.connection.execute("DROP TRIGGER audit_log_no_update")
        self.db.connection.execute("UPDATE audit_log SET action = 'förfalskad' WHERE seq = 1")
        self.assert_enters("revisionsloggen är bruten")

    def test_unauthorized_transaction(self):
        """Verifies SR-08 (§59): en obehörig transaktion i ledgern ger skyddat läge."""
        self.book(15_000, approval=Approval.UNAPPROVED)
        self.assert_enters("obehöriga transaktioner")

    def test_control_function_unavailable(self):
        """Verifies SR-08 (§59): en avstängd CRO gör att en nödvändig kontrollfunktion saknas."""
        self.registry.transition("cro-1", S.SUSPENDED, "yorgo", "test")
        self.assert_enters("kontrollfunktion otillgänglig: cro")

    def test_security_incident(self):
        """Verifies SR-08 (§59): en anmäld säkerhetsincident ger skyddat läge."""
        with self.assertRaises(ProtectedModeError):
            self.mode.report_incident("ceo-1", "x")  # operativ chef kan inte anmäla
        self.mode.report_incident("audit-1", "misstänkt intrång i API-nyckelhanteringen")
        self.assert_enters("säkerhetsincident")

    def test_undecidable_counts_as_reason(self):
        """Verifies SR-08 (§59): kan systemet inte avgöra läget går det in i skyddat läge."""
        self.mode._ledger_figures = lambda: (_ for _ in ()).throw(RuntimeError("trasig"))
        self.assert_enters("kunde inte genomföras")


class TestWhatIsBlocked(ModeCase):
    def setUp(self):
        super().setUp()
        self.mode.report_incident("yorgo", "övning")

    def test_external_and_financial_blocked_harmless_allowed(self):
        """Verifies SR-08 (§59): ekonomiska och externa handlingar blockeras, analys och dokumentation fortsätter."""
        self.assertFalse(self.spend_allowed())
        self.assertIn("SR-08", self.engine.check("lead-1", "research.search").reason)
        for agent_id, tool in (("lead-1", "report.write"), ("lead-1", "llm.complete"), ("ceo-1", "task.create"),
                               ("audit-1", "audit.verify")):
            with self.subTest(tool=tool):
                self.assertTrue(self.engine.check(agent_id, tool).allowed)

    def test_entering_is_logged_once_with_notification(self):
        """Verifies SR-08: inträdet loggas en gång och grundarna anges som mottagare."""
        self.spend_allowed()
        entered = [e for e in self.audit.entries() if e.action == "mode.protected_entered"]
        self.assertEqual(len(entered), 1)
        self.assertEqual(entered[0].details["notify"], ["founders"])


class TestExit(ModeCase):
    def test_exit_only_by_founder_when_conditions_cleared(self):
        """Verifies D-031: bara en grundare lämnar läget, och bara när inget skäl längre gäller."""
        self.registry.transition("cro-1", S.SUSPENDED, "yorgo", "test")
        self.mode.update()
        for actor in ("ceo-1", "cro-1"):
            with self.subTest(actor=actor), self.assertRaises(ProtectedModeError):
                self.mode.exit(actor, "OK")
        with self.assertRaises(ProtectedModeError) as ctx:
            self.mode.exit("yorgo", "OK")
        self.assertIn("gäller fortfarande", str(ctx.exception))
        self.registry.transition("cro-1", S.PROBATION, "yorgo", "tillbaka")
        self.assertFalse(self.mode.exit("yorgo", "CRO tillbaka").protected)
        self.assertTrue(self.spend_allowed())

    def test_unauthorized_entry_can_be_acknowledged(self):
        """Verifies D-031: en grundare kan kvittera en obehörig post uttryckligen, och den räknas sedan inte."""
        entry = self.book(15_000, approval=Approval.UNAPPROVED)
        self.mode.update()
        with self.assertRaises(ProtectedModeError):
            self.mode.exit("robin", "OK")
        self.assertFalse(self.mode.exit("robin", "faktura kontrollerad i efterhand", acknowledge=(entry.entry_id,)).protected)
        self.assertEqual(self.mode.assess(), ())

    def test_incident_cleared_by_exit(self):
        """Verifies D-031: en anmäld incident gäller tills en grundare lämnar läget."""
        self.mode.report_incident("cro-1", "övning")
        self.assertFalse(self.mode.exit("yorgo", "övningen klar").protected)
        self.assertTrue(self.spend_allowed())


class TestKillSwitchAndPersistence(ModeCase):
    def test_broken_bookkeeping_also_engages_kill_switch(self):
        """Verifies SR-08 och SR-07: bruten bokföring aktiverar dessutom nödstoppet om det är kopplat."""
        self.start(kill=True)
        self.book(15_000, approval=Approval.UNAPPROVED)
        self.assertFalse(self.spend_allowed())
        self.assertTrue(self.kill.state().engaged)
        self.assertEqual(self.kill.state().engaged_by, "system:protected-mode")

    def test_survives_restart_and_is_append_only(self):
        """Verifies FR-03 och SR-08: läget gäller efter omstart, och händelserna kan inte ändras."""
        self.mode.report_incident("yorgo", "test")
        self.db.close()
        self.start()
        self.assertTrue(self.mode.state().protected)
        for sql in ("DELETE FROM operating_mode_events", "UPDATE operating_mode_events SET event = 'exited'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)


if __name__ == "__main__":
    unittest.main()
