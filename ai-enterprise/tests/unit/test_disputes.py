"""Tester för src/aie/governance/disputes.py (Fas 3). Verifierar FR-12, FR-13, SR-02 och §21.

Riktiga `config/permissions.toml` och `config/risk_limits.toml`:
HUMAN_APPROVAL_THRESHOLD = 10 000, MAX_SINGLE_TRANSACTION = 20 000 (SIM).
ROADMAP:s nyckeltest för Fas 3 är `test_cfo_and_cro_disagree_is_escalated_with_documented_dispute`.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.config import load_config
from aie.governance import (
    ConflictType,
    DisputeBoard,
    DisputeError,
    DisputeStatus,
    HardLimitViolation,
    Level,
    NeedsApproval,
    Position,
    RiskClass,
)
from aie.memory import Database
from aie.orchestration import TaskBoard
from .fixture_config import TEST_CONFIG

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})
CFO = Position(
    "cfo-1", "Kanalen ger nettovinst inom 60 dagar", ("kalkyl i docs/channels.md",)
)
CRO = Position(
    "cro-1",
    "Risken för kontoavstängning är för hög",
    ("Etsy kräver AI-märkning, SR-18",),
)


class DisputeCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.permissions = load_permissions(TEST_CONFIG)
        self.limits = load_config(TEST_CONFIG).risk
        self.registry = AgentRegistry(self.permissions, self.db)
        self.audit = AuditLog(self.db)
        self.engine = AuthorizationEngine(
            self.permissions, self.registry, "sim", self.audit
        )
        self.board = TaskBoard(self.db, self.registry, self.engine, founders=FOUNDERS)
        self.disputes = DisputeBoard(
            self.db,
            self.board,
            self.registry,
            self.engine,
            self.limits,
            FOUNDERS,
            self.audit,
        )
        for agent_id, role, manager in (
            ("ceo-1", "ceo", None),
            ("cfo-1", "cfo", None),
            ("cro-1", "cro", None),
            ("lead-1", "research_lead", "ceo-1"),
        ):
            self.activate(agent_id, role, manager)
        self.task = self.board.create("ceo-1", "Börja sälja på Etsy?", "D-010")

    def activate(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def open(
        self,
        budget=5_000,
        risk=RiskClass.MEDIUM,
        conflict=ConflictType.RISK,
        positions=(CFO, CRO),
        actor="cfo-1",
    ):
        return self.disputes.open(
            actor,
            self.task.task_id,
            conflict,
            "Öppna en Etsy-butik",
            budget,
            risk,
            positions,
        )

    def actions(self):
        return [e.action for e in self.audit.entries()]


class TestRecorded(DisputeCase):
    def test_claims_evidence_and_conflict_type_are_recorded(self):
        """Verifies FR-12 (§21): exakt vilka påståenden, vilka underlag och vilken typ av konflikt."""
        d = self.open()
        self.assertEqual(d.conflict_type, ConflictType.RISK)
        self.assertEqual(d.positions, (CFO, CRO))
        self.assertEqual(d.parties, frozenset({"cfo-1", "cro-1"}))
        self.assertEqual(d.status, DisputeStatus.OPEN)
        opened = next(e for e in self.audit.entries() if e.action == "dispute.opened")
        self.assertEqual(opened.details["parties"], ["cfo-1", "cro-1"])
        self.assertEqual(opened.details["conflict_type"], "risk")

    def test_all_four_conflict_types(self):
        """Verifies FR-12: konflikten kan gälla mål, data, risk eller metod, och inget annat."""
        self.assertEqual(
            {c.value for c in ConflictType}, {"goal", "data", "risk", "method"}
        )
        for conflict in ConflictType:
            with self.subTest(conflict=conflict.value):
                self.assertEqual(self.open(conflict=conflict).conflict_type, conflict)
        with self.assertRaises(DisputeError):
            self.open(conflict="känsla")

    def test_no_false_consensus_needs_two_different_agents(self):
        """Verifies §21: en tvist kräver ståndpunkter från minst två olika agenter."""
        with self.assertRaises(DisputeError) as ctx:
            self.open(
                positions=(CFO, Position("cfo-1", "Jag håller inte med mig själv", ()))
            )
        self.assertIn("minst två olika agenter", str(ctx.exception))

    def test_unsupported_claim_flagged_and_analysis_requested(self):
        """Verifies §21: ett påstående utan underlag syns, och kompletterande analys kan begäras och loggas."""
        d = self.open(positions=(CFO, Position("cro-1", "Det känns riskabelt", ())))
        self.assertEqual([p.agent_id for p in d.unsupported_claims], ["cro-1"])
        self.disputes.request_analysis(
            "cfo-1", d.dispute_id, "cro-1", "Vilka källor stöder risken?"
        )
        self.assertEqual(
            [e.event for e in self.disputes.events(d.dispute_id)],
            ["opened", "analysis_requested"],
        )
        self.assertIn("dispute.analysis_requested", self.actions())

    def test_positions_and_events_are_append_only(self):
        """Verifies FR-12: ståndpunkter och händelser kan inte ändras eller raderas i efterhand."""
        d = self.open()
        for sql in (
            "UPDATE dispute_positions SET claim = 'ändrat'",
            "DELETE FROM dispute_positions",
            "UPDATE dispute_events SET note = 'x'",
            "DELETE FROM disputes",
        ):
            with (
                self.subTest(sql=sql),
                self.assertRaises(sqlite3.DatabaseError),
                self.db.transaction() as tx,
            ):
                tx.execute(sql)
        self.assertEqual(self.disputes.get(d.dispute_id).positions, (CFO, CRO))


class TestResolve(DisputeCase):
    def test_ceo_resolves_within_limits(self):
        """Verifies §21: CEO (inte part, har dispute.resolve) avgör en tvist inom gränserna; det revideras."""
        d = self.open(budget=5_000)
        resolved = self.disputes.resolve(
            "ceo-1", d.dispute_id, True, "Liten skala först, CRO följer upp"
        )
        self.assertEqual(resolved.status, DisputeStatus.RESOLVED)
        self.assertIn("dispute.resolved", self.actions())

    def test_party_cannot_resolve_own_dispute(self):
        """Verifies §21: en part kan inte avgöra sin egen tvist."""
        d = self.open()
        with self.assertRaises(DisputeError):
            self.disputes.resolve("cfo-1", d.dispute_id, True, "Jag har rätt")

    def test_agent_without_mandate_cannot_resolve(self):
        """Verifies SR-02: en agent utan dispute.resolve nekas, och det revideras."""
        d = self.open()
        with self.assertRaises(PermissionDenied):
            self.disputes.resolve("lead-1", d.dispute_id, True, "Kör")
        self.assertEqual(self.disputes.get(d.dispute_id).status, DisputeStatus.OPEN)
        self.assertEqual(
            [e for e in self.audit.entries() if e.action == "tool.denied"][-1].details[
                "tool"
            ],
            "dispute.resolve",
        )


class TestHardLimits(DisputeCase):
    def test_unanimous_vote_cannot_override_budget_limit(self):
        """Verifies §21: inte ens enhälliga röster kan godta ett förslag över MAX_SINGLE_TRANSACTION."""
        over = self.limits.max_single_transaction.amount_minor + 1
        d = self.open(budget=over)
        votes = {"ceo-1": True, "cfo-1": True, "cro-1": True, "lead-1": True}
        with self.assertRaises(HardLimitViolation) as ctx:
            self.disputes.resolve(
                "ceo-1", d.dispute_id, True, "Alla röstade ja", votes=votes
            )
        self.assertIn("MAX_SINGLE_TRANSACTION", str(ctx.exception))
        after = self.disputes.get(d.dispute_id)
        self.assertEqual(
            (after.status, after.escalated_to),
            (DisputeStatus.ESCALATED, Level.FOUNDERS),
        )
        self.assertIn("dispute.hard_limit_blocked", self.actions())
        self.assertNotIn("dispute.resolved", self.actions())

    def test_not_even_a_founder_can_vote_through_a_hard_limit(self):
        """Verifies §21, D-019: gränsen ändras bara i risk_limits.toml (båda grundarna), aldrig genom resolve."""
        d = self.open(budget=self.limits.max_single_transaction.amount_minor + 1)
        with self.assertRaises(HardLimitViolation):
            self.disputes.resolve(
                "robin",
                d.dispute_id,
                True,
                "Grundaren säger ja",
                votes={"robin": True, "yorgo": True},
            )
        self.assertEqual(
            self.disputes.get(d.dispute_id).status, DisputeStatus.ESCALATED
        )

    def test_critical_risk_cannot_be_voted_through(self):
        """Verifies §21 (säkerhetsgräns): riskklass critical godtas aldrig via resolve, oavsett budget."""
        d = self.open(budget=0, risk=RiskClass.CRITICAL)
        with self.assertRaises(HardLimitViolation) as ctx:
            self.disputes.resolve(
                "ceo-1", d.dispute_id, True, "Vi tar risken", votes={"ceo-1": True}
            )
        self.assertIn("critical", str(ctx.exception))

    def test_rejecting_a_risky_proposal_is_always_allowed(self):
        """Verifies §21: att avslå ett förslag som bryter mot gränser är alltid tillåtet."""
        d = self.open(budget=self.limits.max_single_transaction.amount_minor + 1)
        resolved = self.disputes.resolve(
            "ceo-1", d.dispute_id, False, "För dyrt; avslås"
        )
        self.assertEqual(resolved.status, DisputeStatus.RESOLVED)

    def test_above_approval_threshold_goes_to_founders(self):
        """Verifies D-019, FR-13: inom hårda gränser men över HUMAN_APPROVAL_THRESHOLD → grundarna."""
        threshold = self.limits.human_approval_threshold.amount_minor
        d = self.open(budget=threshold + 1)
        with self.assertRaises(NeedsApproval):
            self.disputes.resolve("ceo-1", d.dispute_id, True, "Värt det")
        self.assertEqual(self.disputes.get(d.dispute_id).escalated_to, Level.FOUNDERS)


class TestEscalation(DisputeCase):
    def test_cfo_and_cro_disagree_is_escalated_with_documented_dispute(self):
        """ROADMAP Fas 3 nyckeltest (FR-12, FR-13): CFO och CRO oense → eskaleras med dokumenterad tvist."""
        d = self.open(budget=5_000)
        level = self.disputes.escalate(
            "cfo-1", d.dispute_id, "CFO och CRO kommer inte överens"
        )
        self.assertEqual(level, Level.CEO)
        after = self.disputes.get(d.dispute_id)
        self.assertEqual(
            (after.status, after.escalated_to), (DisputeStatus.ESCALATED, Level.CEO)
        )
        self.assertEqual(after.positions, (CFO, CRO))  # tvisten finns kvar dokumenterad
        self.assertEqual(
            [e.event for e in self.disputes.events(d.dispute_id)],
            ["opened", "escalated"],
        )
        self.assertIn("dispute.escalated", self.actions())
        self.assertEqual(
            self.disputes.resolve("ceo-1", d.dispute_id, False, "Vänta på R-03").status,
            DisputeStatus.RESOLVED,
        )

    def test_right_level_is_founders_when_ceo_is_a_party(self):
        """Verifies §21 (rätt beslutsnivå): är CEO part går tvisten till grundarna."""
        d = self.open(
            positions=(Position("ceo-1", "Vi ska expandera", ("plan",)), CRO),
            actor="ceo-1",
        )
        self.assertEqual(
            self.disputes.escalate("cro-1", d.dispute_id, "kvarstår"), Level.FOUNDERS
        )
        with self.assertRaises(DisputeError):
            self.disputes.resolve("ceo-1", d.dispute_id, True, "Jag bestämmer")

    def test_escalation_never_goes_down_and_founders_can_finish(self):
        """Verifies FR-13: en tvist hos grundarna kan inte flyttas ned till CEO; en grundare kan avsluta den."""
        d = self.open(budget=self.limits.human_approval_threshold.amount_minor + 1)
        self.assertEqual(
            self.disputes.escalate("cfo-1", d.dispute_id, "över gränsen"),
            Level.FOUNDERS,
        )
        self.assertEqual(
            self.disputes.escalate("cro-1", d.dispute_id, "igen", level=Level.CEO),
            Level.FOUNDERS,
        )
        self.assertEqual(
            self.disputes.resolve("yorgo", d.dispute_id, False, "Inte nu").status,
            DisputeStatus.RESOLVED,
        )
        with self.assertRaises(DisputeError):
            self.disputes.escalate("cfo-1", d.dispute_id, "efteråt")


if __name__ == "__main__":
    unittest.main()
