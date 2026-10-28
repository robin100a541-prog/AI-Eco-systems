"""Tester för src/aie/governance/escalation.py och `python -m aie approvals` (Fas 3).

Verifierar FR-13 (eskalering till rätt nivå, mänskligt godkännande), D-019 (en eller båda
grundarna), §21 (inga godkännanden över hårda gränser) och DR-12 (allt fungerar utan modeller).
HUMAN_APPROVAL_THRESHOLD = 10 000 och MAX_SINGLE_TRANSACTION = 20 000 (SIM) i repots konfiguration.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.config import load_config
from aie.governance import (
    ApprovalError,
    ApprovalQueue,
    ConflictType,
    DecisionDraft,
    DecisionLog,
    DisputeBoard,
    DisputeStatus,
    HardLimitViolation,
    Level,
    NeedsApproval,
    Position,
    RequestKind,
    RequestStatus,
    RiskClass,
)
from aie.governance.decisions import Decision
from aie.llm import (
    ChatRequest,
    DataClass,
    LLMGateway,
    Message,
    NoProviderAvailable,
    ProviderRouter,
    QuotaLedger,
    RuleProvider,
    Slot,
)
from aie.memory import Database
from aie.orchestration import TaskBoard
from .fixture_config import TEST_CONFIG

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})
DRAFT = DecisionDraft(
    chosen_action="Köp en mallpaketlicens",
    reasoning="Sparar 20 timmars arbete",
    evidence=("offert 2026-10-23",),
    budget_minor=5_000,
    risk_class=RiskClass.LOW,
    expected_result="Tre produkter klara inom en vecka",
    stop_conditions="Avbryt om licensen inte tillåter vidareförsäljning",
    follow_up="Research-chefen rapporterar efter en vecka",
)


class EscalationCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.limits = load_config(TEST_CONFIG).risk
        self.build(self.db)
        for agent_id, role, manager in (
            ("ceo-1", "ceo", None),
            ("cfo-1", "cfo", None),
            ("cro-1", "cro", None),
            ("lead-1", "research_lead", "ceo-1"),
            ("res-1", "researcher", "lead-1"),
        ):
            self.registry.register(agent_id, role, manager, "yorgo", "test")
            for state in (S.CREATED, S.TESTING, S.ACTIVE):
                self.registry.transition(agent_id, state, "yorgo", "test")
        self.task = self.board.create("ceo-1", "Skaffa mallar", "")
        self.board.assign("ceo-1", self.task.task_id, "lead-1")
        self.small = self.board.create("lead-1", "Litet inköp", "")
        self.board.assign("lead-1", self.small.task_id, "res-1")

    def build(self, db):
        permissions = load_permissions(TEST_CONFIG)
        self.audit = AuditLog(db)
        self.registry = AgentRegistry(permissions, db)
        self.engine = AuthorizationEngine(permissions, self.registry, "sim", self.audit)
        self.board = TaskBoard(db, self.registry, self.engine, founders=FOUNDERS)
        self.decisions = DecisionLog(
            db, self.board, self.engine, self.limits, FOUNDERS, self.audit
        )
        self.disputes = DisputeBoard(
            db,
            self.board,
            self.registry,
            self.engine,
            self.limits,
            FOUNDERS,
            self.audit,
        )
        self.queue = ApprovalQueue(
            db,
            self.decisions,
            self.disputes,
            self.registry,
            self.limits,
            FOUNDERS,
            self.audit,
        )

    @property
    def threshold(self):
        return self.limits.human_approval_threshold.amount_minor

    def actions(self):
        return [e.action for e in self.audit.entries()]


class TestDecisionsEscalate(EscalationCase):
    def test_within_mandate_and_threshold_is_decided_directly(self):
        """Verifies FR-13: inom mandat och under gränsen behövs ingen eskalering."""
        result = self.queue.submit_decision("lead-1", self.task.task_id, DRAFT)
        self.assertIsInstance(result, Decision)
        self.assertEqual(self.queue.pending(), ())

    def test_above_threshold_needs_one_founder(self):
        """Verifies D-019, D-049, FR-13: över gränsen köas agentens beslut; en grundares godkännande räcker."""
        request = self.queue.submit_decision(
            "lead-1", self.task.task_id, replace(DRAFT, budget_minor=self.threshold + 1)
        )
        self.assertEqual(
            (request.kind, request.required_approvals, request.status),
            (RequestKind.DECISION, 1, RequestStatus.PENDING),
        )
        self.assertEqual(self.decisions.for_task(self.task.task_id), ())
        done = self.queue.approve("yorgo", request.request_id, "OK")
        self.assertEqual(done.status, RequestStatus.APPROVED)
        decision = self.decisions.get(done.outcome_decision)
        self.assertEqual(
            (decision.decided_by, decision.budget_minor),
            ("yorgo", self.threshold + 1),
        )
        for action in (
            "approval.requested",
            "approval.vote",
            "approval.approved",
            "decision.recorded",
        ):
            self.assertIn(action, self.actions())

    def test_single_founder_decides_above_threshold_directly(self):
        """Verifies D-049: grundarna agerar som en; en grundare beslutar över gränsen utan kö."""
        decision = self.queue.submit_decision(
            "robin", self.task.task_id, replace(DRAFT, budget_minor=self.threshold + 1)
        )
        self.assertEqual(
            (decision.decided_by, decision.budget_minor), ("robin", self.threshold + 1)
        )
        self.assertEqual(self.queue.pending(), ())

    def test_outside_mandate_goes_to_one_founder(self):
        """Verifies FR-13, D-019 p. 1: en researcher utan decision.record köas; under gränsen räcker en grundare."""
        request = self.queue.submit_decision("res-1", self.small.task_id, DRAFT)
        self.assertEqual(request.required_approvals, 1)
        self.assertIn("utanför mandatet", request.reason)
        self.assertIn("tool.denied", self.actions())
        done = self.queue.approve("yorgo", request.request_id, "Rimligt")
        self.assertEqual(done.status, RequestStatus.APPROVED)
        self.assertEqual(self.decisions.get(done.outcome_decision).decided_by, "yorgo")

    def test_one_reject_rejects_and_nothing_is_decided(self):
        """Verifies D-019: ett nej från en grundare avslår; inget beslut loggas och ingen kan rösta efteråt."""
        request = self.queue.submit_decision(
            "lead-1", self.task.task_id, replace(DRAFT, budget_minor=self.threshold + 1)
        )
        rejected = self.queue.reject("yorgo", request.request_id, "För dyrt just nu")
        self.assertEqual(rejected.status, RequestStatus.REJECTED)
        self.assertEqual(self.decisions.for_task(self.task.task_id), ())
        with self.assertRaises(ApprovalError):
            self.queue.approve("yorgo", request.request_id)
        with self.assertRaises(ApprovalError):
            self.queue.reject("robin", request.request_id, "")

    def test_only_founders_vote_once_each(self):
        """Verifies D-019: bara grundare röstar, en gång var; ett försök från någon annan nekas och revideras."""
        request = self.queue.submit_decision(
            "lead-1", self.task.task_id, replace(DRAFT, budget_minor=self.threshold + 1)
        )
        for impostor in ("ceo-1", "mallory"):
            with self.subTest(actor=impostor), self.assertRaises(ApprovalError):
                self.queue.approve(impostor, request.request_id)
        self.assertEqual(self.actions().count("approval.denied"), 2)
        self.queue.approve("robin", request.request_id)
        with self.assertRaises(ApprovalError):
            self.queue.approve("robin", request.request_id)
        self.assertEqual(self.queue.get(request.request_id).approvals, ("robin",))

    def test_incomplete_decision_is_not_queued(self):
        """Verifies FR-10: ett ofullständigt beslut går inte att skicka till grundarna."""
        from aie.governance import DecisionError

        with self.assertRaises(DecisionError):
            self.queue.submit_decision(
                "res-1", self.small.task_id, replace(DRAFT, reasoning="")
            )
        self.assertEqual(self.queue.pending(), ())


class TestDisputesAndGovernance(EscalationCase):
    def open_dispute(self, budget):
        return self.disputes.open(
            "cfo-1",
            self.task.task_id,
            ConflictType.RISK,
            "Köp licensen",
            budget,
            RiskClass.MEDIUM,
            (
                Position("cfo-1", "Lönsamt", ("kalkyl",)),
                Position("cro-1", "För riskabelt", ("villkor",)),
            ),
        )

    def test_escalated_dispute_approved_by_founders(self):
        """Verifies FR-13, §21, D-049: en tvist över gränsen men inom hårda gränser avgörs av en grundare."""
        d = self.open_dispute(self.threshold + 1)
        with self.assertRaises(NeedsApproval):
            self.disputes.resolve("ceo-1", d.dispute_id, True, "ja")
        request = self.queue.submit_dispute("ceo-1", d.dispute_id)
        self.assertEqual(
            (request.kind, request.required_approvals), (RequestKind.DISPUTE, 1)
        )
        self.queue.approve("yorgo", request.request_id, "Godkänt")
        self.assertEqual(self.disputes.get(d.dispute_id).status, DisputeStatus.RESOLVED)

    def test_founders_cannot_approve_past_a_hard_limit(self):
        """Verifies §21: inte ens båda grundarna kan godkänna ett förslag över MAX_SINGLE_TRANSACTION; bara avslå."""
        d = self.open_dispute(self.limits.max_single_transaction.amount_minor + 1)
        self.assertEqual(
            self.disputes.escalate("cfo-1", d.dispute_id, "kvarstår"), Level.FOUNDERS
        )
        request = self.queue.submit_dispute("cfo-1", d.dispute_id)
        self.assertIn("hårda gränser", request.reason)
        for founder in ("robin", "yorgo"):
            with self.assertRaises(HardLimitViolation):
                self.queue.approve(founder, request.request_id)
        still = self.queue.get(request.request_id)
        self.assertEqual((still.status, still.approvals), (RequestStatus.PENDING, ()))
        self.assertIn("approval.hard_limit_blocked", self.actions())
        rejected = self.queue.reject(
            "yorgo", request.request_id, "Över gränsen; ändra den i så fall via D-019"
        )
        self.assertEqual(rejected.status, RequestStatus.REJECTED)
        self.assertEqual(self.disputes.get(d.dispute_id).status, DisputeStatus.RESOLVED)

    def test_dispute_not_at_founders_cannot_be_queued(self):
        """Verifies FR-13 (rätt nivå): en tvist som ligger hos CEO hör inte hemma i grundarnas kö."""
        d = self.open_dispute(1_000)
        self.assertEqual(
            self.disputes.escalate("cfo-1", d.dispute_id, "kvarstår"), Level.CEO
        )
        with self.assertRaises(ApprovalError):
            self.queue.submit_dispute("cfo-1", d.dispute_id)

    def test_governance_change_needs_one_founder(self):
        """Verifies D-049: ändring i konstitution, gränser eller mandat kräver en grundare, även utan belopp."""
        request = self.queue.submit_governance(
            "robin", self.task.task_id, "Höj MAX_SINGLE_TRANSACTION till 30 000"
        )
        self.assertEqual((request.required_approvals, request.amount_minor), (1, 0))
        self.assertEqual(
            self.queue.approve("yorgo", request.request_id).status,
            RequestStatus.APPROVED,
        )


class TestDurability(EscalationCase):
    def test_queue_is_append_only_and_survives_restart(self):
        """Verifies FR-03, FR-13: förfrågningar och röster kan inte ändras eller raderas och överlever omstart."""
        request = self.queue.submit_decision(
            "lead-1", self.task.task_id, replace(DRAFT, budget_minor=self.threshold + 1)
        )
        self.queue.approve("robin", request.request_id, "ok")
        for sql in (
            "UPDATE approval_votes SET verdict = 'reject'",
            "DELETE FROM approval_votes",
            "DELETE FROM approval_requests",
        ):
            with (
                self.subTest(sql=sql),
                self.assertRaises(sqlite3.DatabaseError),
                self.db.transaction() as tx,
            ):
                tx.execute(sql)
        self.db.close()
        db = Database.open(self.dir / "data", "sim")
        self.addCleanup(db.close)
        self.build(db)
        after = self.queue.get(request.request_id)
        self.assertEqual((after.approvals, after.status), (("robin",), RequestStatus.APPROVED))
        self.assertTrue(AuditLog(db).verify().ok)

    def test_works_when_all_model_quotas_are_exhausted(self):
        """Verifies DR-12: med alla kvoter slut kan agenten inte fråga en modell, men eskalering och beslut fungerar ändå."""
        router = ProviderRouter(
            (Slot(RuleProvider(), 0, 0),),
            QuotaLedger(self.db, day=lambda: "2026-10-23"),
            self.audit,
        )
        gateway = LLMGateway(router, self.engine, self.audit)
        with self.assertRaises(NoProviderAvailable):
            gateway.complete(
                "lead-1",
                ChatRequest((Message("user", "Ska vi köpa?"),), DataClass.INTERNAL),
            )
        request = self.queue.submit_decision(
            "lead-1", self.task.task_id, replace(DRAFT, budget_minor=self.threshold + 1)
        )
        self.assertEqual(
            self.queue.approve("yorgo", request.request_id).status,
            RequestStatus.APPROVED,
        )

    def test_governance_code_never_calls_a_model_directly(self):
        """Verifies DR-12, SR-01: styrmodulerna använder aldrig ProviderRouter eller en leverantör direkt."""
        for path in (ROOT / "src" / "aie" / "governance").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("ProviderRouter", "OpenAICompatibleProvider", "urllib"):
                self.assertNotIn(forbidden, text, f"{path.name} använder {forbidden}")


class TestCli(EscalationCase):
    """`python -m aie approvals` i en egen process mot en riktig databas."""

    def setUp(self):
        super().setUp()
        system = (TEST_CONFIG / "system.toml").read_text(encoding="utf-8")
        system = system.replace(
            'data_dir = "data"', f"data_dir = {json.dumps(str(self.dir / 'data'))}"
        )
        system = system.replace(
            'log_dir = "logs"', f"log_dir = {json.dumps(str(self.dir / 'logs'))}"
        )
        config_dir = self.dir / "config"
        config_dir.mkdir()
        (config_dir / "system.toml").write_text(system, encoding="utf-8")
        for name in ("risk_limits.toml", "permissions.toml"):
            (config_dir / name).write_text(
                (TEST_CONFIG / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
        self.config_dir = config_dir
        self.request = self.queue.submit_decision(
            "lead-1", self.task.task_id, replace(DRAFT, budget_minor=self.threshold + 1)
        )

    def cli(self, *args):
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
        }
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "aie",
                "approvals",
                *args,
                "--config-dir",
                str(self.config_dir),
            ],
            cwd=self.dir,
            env=env,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    def test_list_approve_and_audit_via_cli(self):
        """Verifies FR-13, D-049: CLI:t listar väntande förfrågningar och en grundare godkänner; allt revideras."""
        listed = self.cli("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(f"#{self.request.request_id} [pending] decision", listed.stdout)
        self.assertIn("kräver 1 grundare", listed.stdout)
        done = self.cli(
            "approve", str(self.request.request_id), "--as", "robin", "--note", "ok"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("[approved]", done.stdout)
        self.assertIn("Inga förfrågningar", self.cli("list").stdout)
        self.assertGreaterEqual(self.actions().count("approval.vote"), 1)
        self.assertIn("approval.approved", self.actions())

    def test_cli_reject_needs_note_and_non_founder_is_refused(self):
        """Verifies FR-13, D-019: avslag kräver motivering, och någon som inte är grundare får kod 1 och revideras."""
        impostor = self.cli("approve", str(self.request.request_id), "--as", "ceo-1")
        self.assertEqual(impostor.returncode, 1)
        self.assertIn("inte grundare", impostor.stderr)
        self.assertIn("approval.denied", self.actions())
        no_note = self.cli("reject", str(self.request.request_id), "--as", "yorgo")
        self.assertEqual(no_note.returncode, 1)
        rejected = self.cli(
            "reject", str(self.request.request_id), "--as", "yorgo", "--note", "Inte nu"
        )
        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        self.assertIn("[rejected]", rejected.stdout)


if __name__ == "__main__":
    unittest.main()
