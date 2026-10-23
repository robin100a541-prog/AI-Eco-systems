"""Tester för src/aie/governance/decisions.py (Fas 3). Verifierar FR-10, SR-01, SR-02, SR-10 och §51.

Riktiga `config/permissions.toml` och `config/risk_limits.toml` (HUMAN_APPROVAL_THRESHOLD = 10 000 SIM).
"""

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.config import load_config
from aie.governance import (
    DecisionDraft,
    DecisionError,
    DecisionLog,
    NeedsApproval,
    RiskClass,
)
from aie.memory import Database
from aie.orchestration import TaskBoard

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})


def draft(**changes):
    base = DecisionDraft(
        chosen_action="Testa Gumroad med en produkt i liten skala",
        reasoning="Låg avgift och moms sköts av plattformen",
        evidence=(
            "docs/channels.md: Gumroad 10 % + 0,50 USD",
            "R-02 i research/QUESTIONS.md",
        ),
        budget_minor=5_000,
        risk_class=RiskClass.LOW,
        expected_result="Minst en försäljning inom 30 dagar",
        stop_conditions="Avbryt om kostnaden passerar budgeten eller ingen försäljning på 30 dagar",
        follow_up="CFO jämför utfall mot prognos efter 30 dagar",
    )
    return replace(base, **changes)


class DecisionCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.open_db()
        self.permissions = load_permissions(ROOT / "config")
        self.limits = load_config(ROOT / "config").risk
        self.registry = AgentRegistry(self.permissions, self.db)
        self.audit = AuditLog(self.db)
        self.engine = AuthorizationEngine(
            self.permissions, self.registry, "sim", self.audit
        )
        self.board = TaskBoard(self.db, self.registry, self.engine, founders=FOUNDERS)
        self.log = DecisionLog(
            self.db, self.board, self.engine, self.limits, FOUNDERS, self.audit
        )
        # Hierarkin (D-020): departementschefen rapporterar till CEO, arbetsagenten till sin chef.
        for agent_id, role, manager in (
            ("ceo-1", "ceo", None),
            ("lead-1", "research_lead", "ceo-1"),
            ("res-1", "researcher", "lead-1"),
        ):
            self.activate(agent_id, role, manager)
        self.task = self.board.create("ceo-1", "Välj försäljningskanal", "D-010")
        self.board.assign("ceo-1", self.task.task_id, "lead-1")

    def open_db(self):
        db = Database.open(self.dir / "data", "sim")
        self.addCleanup(db.close)
        return db

    def activate(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def actions(self):
        return [e.action for e in self.audit.entries()]


class TestRecord(DecisionCase):
    def test_decision_has_all_eight_fields_and_is_audited(self):
        """Verifies FR-10 (§20 steg 7): beslutet sparar alla åtta fält och revideras."""
        d = self.log.record("lead-1", self.task.task_id, draft())
        self.assertEqual(d.task_id, self.task.task_id)
        self.assertEqual(d.decided_by, "lead-1")
        self.assertEqual(
            (d.budget_minor, d.currency, d.risk_class), (5_000, "SIM", RiskClass.LOW)
        )
        for field in (
            "chosen_action",
            "reasoning",
            "expected_result",
            "stop_conditions",
            "follow_up",
        ):
            self.assertTrue(getattr(d, field))
        self.assertEqual(len(d.evidence), 2)
        recorded = [e for e in self.audit.entries() if e.action == "decision.recorded"]
        self.assertEqual(recorded[0].details["decision_id"], d.decision_id)
        self.assertEqual(recorded[0].details["task_id"], self.task.task_id)

    def test_missing_fields_rejected_all_at_once(self):
        """Verifies FR-10: ett beslut utan motivering, underlag eller stoppvillkor sparas inte; alla fel listas."""
        with self.assertRaises(DecisionError) as ctx:
            self.log.record(
                "lead-1",
                self.task.task_id,
                draft(reasoning=" ", evidence=(), stop_conditions=""),
            )
        for fragment in (
            "reasoning saknas",
            "evidence måste",
            "stop_conditions saknas",
        ):
            self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(self.log.for_task(self.task.task_id), ())

    def test_decision_needs_existing_task(self):
        """Verifies §51: ett beslut kan inte finnas utan uppgift, varken via kod eller SQL."""
        with self.assertRaises(DecisionError):
            self.log.record("robin", 999, draft())
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO decisions (task_id, decided_by, chosen_action, reasoning, evidence, budget_minor, "
                "currency, risk_class, expected_result, stop_conditions, follow_up, decided_at) "
                "VALUES (999, 'x', 'a', 'b', '[\"c\"]', 0, 'SIM', 'low', 'd', 'e', 'f', 't')"
            )

    def test_secret_in_decision_rejected(self):
        """Verifies SR-10: en hemlighet i fritexten sparas aldrig i den oföränderliga loggen."""
        with self.assertRaises(DecisionError) as ctx:
            self.log.record(
                "lead-1",
                self.task.task_id,
                draft(reasoning="använd api_key=sk-123 mot Gumroad"),
            )
        self.assertIn("hemlighet", str(ctx.exception))
        self.assertEqual(self.log.for_task(self.task.task_id), ())


class TestAuthority(DecisionCase):
    def test_role_without_mandate_denied_and_logged(self):
        """Verifies SR-02 (§51 beslut inom befogenheter): en researcher saknar decision.record och nekas; det revideras."""
        task = self.board.create("ceo-1", "Litet test", "")
        self.board.assign("ceo-1", task.task_id, "res-1")
        with self.assertRaises(PermissionDenied):
            self.log.record("res-1", task.task_id, draft())
        self.assertEqual(self.log.for_task(task.task_id), ())
        denied = [e for e in self.audit.entries() if e.action == "tool.denied"]
        self.assertEqual(denied[-1].details["tool"], "decision.record")

    def test_agent_cannot_decide_on_someone_elses_task(self):
        """Verifies SR-01: en agent med mandat får bara besluta om uppgifter den äger eller har skapat."""
        self.activate("cfo-1", "cfo")
        with self.assertRaises(DecisionError) as ctx:
            self.log.record("cfo-1", self.task.task_id, draft())
        self.assertIn("äger inte", str(ctx.exception))

    def test_over_threshold_needs_approval_for_agent_and_single_founder(self):
        """Verifies D-019 (§51): över HUMAN_APPROVAL_THRESHOLD får varken agent eller ensam grundare besluta."""
        threshold = self.limits.human_approval_threshold.amount_minor
        for actor in ("lead-1", "robin"):
            with self.subTest(actor=actor), self.assertRaises(NeedsApproval) as ctx:
                self.log.record(
                    actor, self.task.task_id, draft(budget_minor=threshold + 1)
                )
            self.assertIn("båda grundarna", str(ctx.exception))
        self.assertEqual(self.log.for_task(self.task.task_id), ())
        at_limit = self.log.record(
            "lead-1", self.task.task_id, draft(budget_minor=threshold)
        )
        self.assertEqual(at_limit.budget_minor, threshold)

    def test_founder_can_decide_on_any_task_below_threshold(self):
        """Verifies D-019: en grundare räcker upp till gränsen, även utan att äga uppgiften."""
        self.assertEqual(
            self.log.record("yorgo", self.task.task_id, draft()).decided_by, "yorgo"
        )

    def test_suspended_head_cannot_decide(self):
        """Verifies SR-02: en avstängd agent fattar inga beslut, inte ens om sin egen uppgift."""
        self.registry.transition("lead-1", S.SUSPENDED, "yorgo", "granskas")
        with self.assertRaises(PermissionDenied):
            self.log.record("lead-1", self.task.task_id, draft())


class TestTraceability(DecisionCase):
    def test_trace_from_decision_back_to_task_and_history(self):
        """Verifies §51 (spårbarhet uppgift → beslut): från beslutet nås uppgiften, dess historik och alla beslut."""
        first = self.log.record("lead-1", self.task.task_id, draft())
        second = self.log.record(
            "lead-1",
            self.task.task_id,
            draft(budget_minor=3_000, supersedes=first.decision_id),
        )
        trace = self.log.trace(second.decision_id)
        self.assertEqual(trace.task.task_id, self.task.task_id)
        self.assertEqual([e.event for e in trace.task_events], ["created", "assigned"])
        self.assertEqual(
            [d.decision_id for d in trace.decisions],
            [first.decision_id, second.decision_id],
        )
        self.assertEqual(trace.decisions[1].supersedes, first.decision_id)

    def test_supersedes_must_be_same_task(self):
        """Verifies §51: ett beslut kan bara ersätta ett beslut om samma uppgift."""
        other = self.board.create("ceo-1", "Annan uppgift", "")
        old = self.log.record("robin", other.task_id, draft())
        with self.assertRaises(DecisionError):
            self.log.record(
                "lead-1", self.task.task_id, draft(supersedes=old.decision_id)
            )

    def test_decisions_are_append_only_and_survive_restart(self):
        """Verifies FR-10, FR-03: beslut kan inte ändras eller raderas och finns kvar efter omstart."""
        d = self.log.record("lead-1", self.task.task_id, draft())
        for sql in ("UPDATE decisions SET budget_minor = 0", "DELETE FROM decisions"):
            with (
                self.subTest(sql=sql),
                self.assertRaises(sqlite3.DatabaseError),
                self.db.transaction() as tx,
            ):
                tx.execute(sql)
        self.db.close()
        db = self.open_db()
        registry = AgentRegistry(self.permissions, db)
        engine = AuthorizationEngine(self.permissions, registry, "sim", AuditLog(db))
        board = TaskBoard(db, registry, engine, founders=FOUNDERS)
        log = DecisionLog(db, board, engine, self.limits, FOUNDERS, AuditLog(db))
        self.assertEqual(log.get(d.decision_id), d)
        self.assertTrue(AuditLog(db).verify().ok)


if __name__ == "__main__":
    unittest.main()
