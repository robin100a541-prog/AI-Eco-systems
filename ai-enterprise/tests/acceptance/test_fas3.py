"""Acceptanstester för Fas 3 (konstitutionen §51, ROADMAP Fas 3).

Hela kedjan byggs som `python -m aie approvals` bygger den (`aie.governance.cli.build`), med de
riktiga konfigurationsfilerna i `config/` och en riktig databas: register → befälskedja →
Authorization Engine med kontrollstopp → uppgifter → samråd → beslutslogg → tvister →
grundarnas godkännandekö → revisionsloggen. Ingen språkmodell används; allt är regelstyrt.

§51 acceptanskriterier:
1. Uppgifter går till rätt ansvarig roll.            → TestRightRole
2. Beslut fattas endast inom tillåtna befogenheter.  → TestAuthority (med ROADMAP:s första nyckeltest)
3. Konflikter dokumenteras.                          → TestConflictsDocumented
4. Eskalering fungerar.                              → TestEscalation (med ROADMAP:s andra nyckeltest)
5. Det finns spårbarhet från uppgift till beslut.    → TestTraceability
"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentState
from aie.authorization import PermissionDenied
from aie.collaboration.consultation import ConsultationBoard
from aie.collaboration.consultation import Position as Opinion
from aie.collaboration.consultation import RiskClass as ConsultRisk
from aie.config import load_config
from aie.governance import (
    ConflictType,
    DecisionDraft,
    DisputeStatus,
    HardLimitViolation,
    Level,
    NeedsApproval,
    Position,
    RequestStatus,
    RiskClass,
)
from aie.governance.cli import build
from aie.memory import Database
from aie.orchestration import TaskError, TaskStatus

ROOT = Path(__file__).resolve().parents[2]
ORG = (  # §8: grundare → CEO → Research-chef → forskare; kontrollfunktionerna direkt under grundarna
    ("ceo-1", "ceo", None),
    ("cfo-1", "cfo", None),
    ("cro-1", "cro", None),
    ("comp-1", "compliance", None),
    ("audit-1", "auditor", None),
    ("lead-1", "research_lead", "ceo-1"),
    ("res-1", "researcher", "lead-1"),
)
DRAFT = DecisionDraft(
    chosen_action="Testa en Etsy-butik med tre mallar",
    reasoning="Kalkylen visar nettovinst inom 60 dagar",
    evidence=("task:1", "file:docs/channels.md"),
    budget_minor=5_000,
    risk_class=RiskClass.MEDIUM,
    expected_result="Minst tio försäljningar på 30 dagar",
    stop_conditions="Avbryt om förlusten når 2 000 SIM",
    follow_up="Research-chefen rapporterar varje vecka",
)
CFO_VIEW = Position(
    "cfo-1", "Kanalen ger nettovinst inom 60 dagar", ("file:docs/channels.md",)
)
CRO_VIEW = Position(
    "cro-1",
    "Risken för kontoavstängning är för hög",
    ("url:https://www.etsy.com/legal/policy",),
)


class Fas3Acceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config = load_config(ROOT / "config")
        self.start_system()
        for agent_id, role, manager in ORG:
            self.gov.registry.register(agent_id, role, manager, "yorgo", "MVP")
            for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                self.gov.registry.transition(
                    agent_id, state, "yorgo", "godkända tester"
                )
        # CEO tar emot uppdraget från grundarna och delar ut det nedåt (§8 nivå 1 och 3).
        self.task = self.gov.board.create(
            "robin", "Utred försäljning av mallar på Etsy", "D-010"
        )
        self.gov.board.assign("robin", self.task.task_id, "ceo-1")
        self.gov.board.assign("ceo-1", self.task.task_id, "lead-1")

    def start_system(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.gov = build(self.config, self.db, ROOT / "config")
        self.founders = frozenset(self.config.system.founders)

    @property
    def threshold(self):
        return self.config.risk.human_approval_threshold.amount_minor

    def actions(self):
        return [e.action for e in self.gov.audit.entries()]


class TestRightRole(Fas3Acceptance):
    def test_work_flows_down_the_chain_to_the_worker_who_does_it(self):
        """§51 kriterium 1 (FR-09, D-023): grundare → CEO → Research-chef → forskare, och forskaren slutför."""
        board = self.gov.board
        subtask = board.create("lead-1", "Jämför Etsys avgifter med Gumroad")
        board.assign("lead-1", subtask.task_id, "res-1")
        board.start("res-1", subtask.task_id)
        done = board.complete("res-1", subtask.task_id, "Rapport: report:1")
        self.assertEqual((done.status, done.owner_id), (TaskStatus.DONE, "res-1"))
        self.assertEqual(
            [(e.event, e.actor) for e in board.events(self.task.task_id)],
            [("created", "robin"), ("assigned", "robin"), ("reassigned", "ceo-1")],
        )

    def test_tasks_cannot_go_outside_the_chain_of_command(self):
        """§51 kriterium 1 (§8 nivå 2, D-020, D-023): ingen ger order uppåt, till ett annat team eller till kontrollen."""
        for actor, owner in (
            ("lead-1", "cfo-1"),
            ("lead-1", "ceo-1"),
            ("ceo-1", "cfo-1"),
            ("ceo-1", "audit-1"),
        ):
            with self.subTest(actor=actor, owner=owner):
                task = self.gov.board.create("robin", "Felriktad uppgift")
                with self.assertRaisesRegex(TaskError, "befälskedja"):
                    self.gov.board.assign(actor, task.task_id, owner)
        with self.assertRaises(
            PermissionDenied
        ):  # arbetsagenten har inte ens mandatet att fördela
            self.gov.board.assign("res-1", self.task.task_id, "lead-1")


class TestAuthority(Fas3Acceptance):
    def test_ceo_cannot_raise_own_limit(self):
        """ROADMAP Fas 3 nyckeltest 1 (SR-04): CEO försöker höja sin egen gräns → nekas och loggas."""
        for tool in (
            "governance.change_limits",
            "governance.change_mandate",
            "governance.change_constitution",
        ):
            with self.subTest(tool=tool), self.assertRaises(PermissionDenied):
                self.gov.engine.require("ceo-1", tool)
        self.assertGreaterEqual(self.actions().count("tool.denied"), 3)

    def test_decisions_only_within_mandate_and_threshold(self):
        """§51 kriterium 2 (FR-10, D-019): rätt roll beslutar inom gränsen; utan mandat eller över gränsen gör ingen det."""
        log = self.gov.decisions
        decision = log.record("lead-1", self.task.task_id, DRAFT)
        self.assertEqual(decision.decided_by, "lead-1")
        sub = self.gov.board.create("lead-1", "Ta fram mallarna")
        self.gov.board.assign("lead-1", sub.task_id, "res-1")
        with self.assertRaises(PermissionDenied):  # forskaren har inte decision.record
            log.record("res-1", sub.task_id, DRAFT)
        with self.assertRaises(NeedsApproval):  # över HUMAN_APPROVAL_THRESHOLD
            log.record(
                "lead-1",
                self.task.task_id,
                replace(DRAFT, budget_minor=self.threshold + 1),
            )
        with self.assertRaises(
            NeedsApproval
        ):  # inte ens en ensam grundare över gränsen (D-019)
            log.record(
                "robin",
                self.task.task_id,
                replace(DRAFT, budget_minor=self.threshold + 1),
            )
        self.assertEqual(
            [d.decision_id for d in log.for_task(self.task.task_id)],
            [decision.decision_id],
        )

    def test_control_function_stop_removes_the_mandate(self):
        """§51 kriterium 2 (SR-05): när CRO stoppar Research får chefen inte längre besluta."""
        stops = self.gov.engine._stops
        stop = stops.place(
            "cro-1", "department", "research", "Kontoavstängningsrisk utreds"
        )
        with self.assertRaises(PermissionDenied) as caught:
            self.gov.decisions.record("lead-1", self.task.task_id, DRAFT)
        self.assertIn("SR-05", str(caught.exception))
        stops.lift("cro-1", stop.stop_id, "Utrett")
        self.assertEqual(
            self.gov.decisions.record("lead-1", self.task.task_id, DRAFT).decided_by,
            "lead-1",
        )


class TestConflictsDocumented(Fas3Acceptance):
    def test_dispute_keeps_claims_evidence_and_conflict_type(self):
        """§51 kriterium 3 (FR-12, §21): påståenden, underlag och konflikttyp sparas och överlever en omstart."""
        d = self.gov.disputes.open(
            "cfo-1",
            self.task.task_id,
            ConflictType.RISK,
            "Öppna en Etsy-butik",
            5_000,
            RiskClass.MEDIUM,
            (CFO_VIEW, CRO_VIEW),
        )
        self.db.close()
        self.start_system()
        kept = self.gov.disputes.get(d.dispute_id)
        self.assertEqual(
            (kept.conflict_type, kept.positions),
            (ConflictType.RISK, (CFO_VIEW, CRO_VIEW)),
        )
        self.assertEqual(
            [x.dispute_id for x in self.gov.disputes.for_task(self.task.task_id)],
            [d.dispute_id],
        )
        self.assertIn("dispute.opened", self.actions())

    def test_consultation_objection_is_kept_not_voted_away(self):
        """§51 kriterium 3 (FR-11, §20 steg 5): en invändning i samrådet står kvar med sitt underlag."""
        board = ConsultationBoard(
            self.db,
            self.gov.registry,
            self.gov.engine._permissions,
            self.gov.audit,
            self.founders,
            self.config.risk.human_approval_threshold,
        )
        c = board.open(
            "ceo-1",
            "Etsy-butik",
            "Ska vi öppna?",
            ConsultRisk.MEDIUM,
            self.config.risk.human_approval_threshold.__class__(5_000, "SIM"),
        )
        board.respond(
            "cfo-1",
            c.consultation_id,
            Opinion.SUPPORT,
            "Lönsamt enligt kalkylen",
            ("file:docs/channels.md",),
        )
        done = board.respond(
            "cro-1",
            c.consultation_id,
            Opinion.OBJECT,
            "För hög risk",
            ("url:https://www.etsy.com/legal/policy",),
        )
        self.assertTrue(done.complete)
        self.assertFalse(done.unanimous)
        self.assertEqual([o.position for o in done.objections], [Opinion.OBJECT])


class TestEscalation(Fas3Acceptance):
    def open_dispute(self, budget):
        return self.gov.disputes.open(
            "cfo-1",
            self.task.task_id,
            ConflictType.RISK,
            "Öppna en Etsy-butik",
            budget,
            RiskClass.MEDIUM,
            (CFO_VIEW, CRO_VIEW),
        )

    def test_cfo_and_cro_disagree_is_escalated_with_documented_dispute(self):
        """ROADMAP Fas 3 nyckeltest 2 (FR-13): CFO och CRO oense → eskaleras med dokumenterad tvist; CEO avgör."""
        d = self.open_dispute(5_000)
        self.assertEqual(
            self.gov.disputes.escalate("cfo-1", d.dispute_id, "Vi kommer inte överens"),
            Level.CEO,
        )
        resolved = self.gov.disputes.resolve(
            "ceo-1", d.dispute_id, False, "Vänta på Compliance"
        )
        self.assertEqual(resolved.status, DisputeStatus.RESOLVED)
        self.assertEqual(
            [e.event for e in self.gov.disputes.events(d.dispute_id)],
            ["opened", "escalated", "resolved"],
        )

    def test_above_threshold_goes_to_both_founders(self):
        """§51 kriterium 4 (FR-13, D-019): över gränsen eskaleras till grundarnas kö och kräver båda."""
        d = self.open_dispute(self.threshold + 1)
        self.assertEqual(
            self.gov.disputes.escalate("cfo-1", d.dispute_id, "Över gränsen"),
            Level.FOUNDERS,
        )
        request = self.gov.queue.submit_dispute("cfo-1", d.dispute_id)
        self.assertEqual(request.required_approvals, 2)
        self.assertEqual(
            self.gov.queue.approve("robin", request.request_id).status,
            RequestStatus.PENDING,
        )
        self.assertEqual(
            self.gov.queue.approve("yorgo", request.request_id).status,
            RequestStatus.APPROVED,
        )
        self.assertEqual(
            self.gov.disputes.get(d.dispute_id).status, DisputeStatus.RESOLVED
        )
        for action in (
            "dispute.escalated",
            "approval.requested",
            "approval.vote",
            "approval.approved",
        ):
            self.assertIn(action, self.actions())

    def test_outside_mandate_goes_to_a_founder(self):
        """§51 kriterium 4 (§8 nivå 1, D-019): ett beslut utanför agentens mandat hamnar hos grundarna."""
        sub = self.gov.board.create("lead-1", "Köp mallpaket")
        self.gov.board.assign("lead-1", sub.task_id, "res-1")
        request = self.gov.queue.submit_decision("res-1", sub.task_id, DRAFT)
        self.assertIn("utanför mandatet", request.reason)
        self.assertEqual(request.required_approvals, 1)
        self.assertEqual(
            self.gov.queue.approve("yorgo", request.request_id).status,
            RequestStatus.APPROVED,
        )

    def test_no_one_can_approve_past_a_hard_limit(self):
        """§51 kriterium 4 (§21): inte ens båda grundarna godkänner över MAX_SINGLE_TRANSACTION; bara avslag."""
        d = self.open_dispute(self.config.risk.max_single_transaction.amount_minor + 1)
        self.gov.disputes.escalate("cfo-1", d.dispute_id, "Över gränsen")
        request = self.gov.queue.submit_dispute("cfo-1", d.dispute_id)
        for founder in sorted(self.founders):
            with self.assertRaises(HardLimitViolation):
                self.gov.queue.approve(founder, request.request_id)
        rejected = self.gov.queue.reject(
            "robin", request.request_id, "Över MAX_SINGLE_TRANSACTION"
        )
        self.assertEqual(rejected.status, RequestStatus.REJECTED)


class TestTraceability(Fas3Acceptance):
    def test_from_decision_back_to_task_history_and_approvals(self):
        """§51 kriterium 5 (FR-10): från beslutet nås uppgiften, dess historik och grundarnas godkännande."""
        request = self.gov.queue.submit_decision(
            "lead-1", self.task.task_id, replace(DRAFT, budget_minor=self.threshold + 1)
        )
        self.gov.queue.approve("robin", request.request_id, "OK")
        approved = self.gov.queue.approve("yorgo", request.request_id, "OK")
        self.db.close()
        self.start_system()  # spårbarheten överlever en omstart
        trace = self.gov.decisions.trace(approved.outcome_decision)
        self.assertEqual(trace.task.task_id, self.task.task_id)
        self.assertEqual(
            [e.event for e in trace.task_events], ["created", "assigned", "reassigned"]
        )
        self.assertEqual(trace.decisions[-1].decided_by, "robin+yorgo")
        self.assertEqual(
            self.gov.queue.get(request.request_id).outcome_decision,
            trace.decisions[-1].decision_id,
        )
        self.assertTrue(self.gov.audit.verify().ok)


if __name__ == "__main__":
    unittest.main()
