"""Tester för godkända utgifter (F5, D-053). Verifierar D-053, D-049, ER-14, ER-03, §21 och FR-20."""
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import (
    BudgetEngine,
    Risk,
    SpendApprovalError,
    SpendApprovals,
    SpendRequest,
    load_budgets,
)
from aie.config import load_config
from aie.config.models import Money
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.llm.gateway import LLMGateway
from aie.llm.providers import RuleProvider
from aie.llm.router import ProviderRouter, QuotaLedger, Slot
from aie.memory import Database
from aie.simulation import SimClock, Simulation, WorkCycle, ensure_org, load_scenario
from aie.system import build_system

from .fixture_config import TEST_CONFIG

FOUNDERS = frozenset({"robin", "yorgo"})


class Clock:
    def __init__(self):
        self.now = datetime(2027, 3, 1, 12, tzinfo=UTC)

    def text(self):
        return self.now.isoformat(timespec="seconds")


class ApprovalCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.clock = Clock()
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(TEST_CONFIG)
        departments = {m.department for m in permissions.roles.values()}
        self.limits = replace(load_config(TEST_CONFIG).risk, human_approval_threshold=Money(1_000, "SIM"))
        self.audit = AuditLog(self.db)
        auth = AuthorizationEngine(permissions, AgentRegistry(permissions, self.db), "sim", self.audit)
        self.ledger = Ledger(self.db, auth, departments, FOUNDERS, self.audit, 1_000)
        self.approvals = SpendApprovals(self.db, self.audit, FOUNDERS, clock=self.clock.text)
        self.budgets = load_budgets(TEST_CONFIG, departments, self.limits)
        self.engine = BudgetEngine(self.ledger, self.limits, self.budgets, self.audit, clock=lambda: self.clock.now,
                                   approvals=self.approvals)
        self.ledger.record("robin", EntryDraft("start", "finance", 1_000_000, "SIM", EntryType.CAPITAL_IN, "start",
                                               Approval.APPROVED, ("decision:start",), status=Status.SETTLED))

    def ask(self, amount=5_000, department="research", initiative="etsy", approval_id=None):
        return self.engine.check("lead-1", SpendRequest(department, amount, "SIM", initiative, Risk.LOW),
                                 approval_id=approval_id)

    def approved(self, amount=5_000, department="research", initiative="etsy"):
        a = self.approvals.request("lead-1", department, initiative, amount, "SIM", "annonser")
        return self.approvals.approve("yorgo", a.approval_id, "ok").approval_id


class TestApproval(ApprovalCase):
    def test_without_approval_the_answer_is_no(self):
        """Verifies ER-14 och D-049: över tröskeln är svaret nej utan en grundares godkännande."""
        check = self.ask()
        self.assertFalse(check.allowed)
        self.assertEqual((check.required_approvals, check.blocked), (1, ()))

    def test_a_valid_approval_allows_exactly_once(self):
        """Verifies D-053: ett giltigt godkännande ger ja exakt en gång; återanvändning ger nej."""
        approval_id = self.approved()
        self.assertTrue(self.ask(approval_id=approval_id).allowed)
        self.assertEqual(self.approvals.get(approval_id).status, "consumed")
        again = self.ask(approval_id=approval_id)
        self.assertFalse(again.allowed)
        self.assertTrue(any("consumed" in r for r in again.blocked))

    def test_wrong_department_initiative_amount_or_age_is_refused(self):
        """Verifies D-053: fel departement, fel initiativ, för stort belopp eller för gammalt godkännande ger nej."""
        cases = (dict(department="finance"), dict(initiative="annat"), dict(amount=5_001))
        for change in cases:
            approval_id = self.approved()
            with self.subTest(change=change):
                check = self.ask(approval_id=approval_id, **change)
                self.assertFalse(check.allowed)
                self.assertEqual(self.approvals.get(approval_id).status, "approved")  # inte förbrukat
        approval_id = self.approved()
        self.clock.now += timedelta(days=8)
        self.assertTrue(any("äldre än 7 dagar" in r for r in self.ask(approval_id=approval_id).blocked))

    def test_an_approval_never_bypasses_hard_limits(self):
        """Verifies §21 och D-053: ett godkännande tar inte bort MAX_SINGLE_TRANSACTION eller budgeten."""
        approval_id = self.approved(amount=25_000)  # MAX_SINGLE_TRANSACTION i testvärdena är 20 000
        check = self.ask(amount=25_000, approval_id=approval_id)
        self.assertFalse(check.allowed)
        self.assertTrue(any("MAX_SINGLE_TRANSACTION" in r for r in check.blocked))
        self.assertEqual(self.approvals.get(approval_id).status, "approved")

    def test_only_founders_decide_and_only_once(self):
        """Verifies D-049 och D-053: bara en grundare beslutar, och en förfrågan får högst ett beslut."""
        a = self.approvals.request("lead-1", "research", "etsy", 5_000, "SIM", "annonser")
        with self.assertRaises(SpendApprovalError):
            self.approvals.approve("ceo-1", a.approval_id, "ok")
        self.approvals.reject("robin", a.approval_id, "för dyrt")
        with self.assertRaises(SpendApprovalError):
            self.approvals.approve("yorgo", a.approval_id, "ändå")
        self.assertFalse(self.ask(approval_id=a.approval_id).allowed)

    def test_two_simultaneous_attempts_cannot_use_the_same_approval(self):
        """Verifies D-053: två samtidiga försök från två anslutningar förbrukar godkännandet högst en gång."""
        approval_id = self.approved()
        barrier, results, errors = threading.Barrier(2), [], []

        def attempt():
            db = Database.open(self.dir / "data", "sim")  # en egen anslutning per tråd, som två processer
            try:
                approvals = SpendApprovals(db, AuditLog(db), FOUNDERS, clock=self.clock.text)
                barrier.wait()
                results.append(approvals.consume(approval_id, "lead-1", "samtidigt"))
            except Exception as exc:  # noqa: BLE001 — testet ska visa felet, inte svälja det
                errors.append(exc)
            finally:
                db.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [False, True])


class TestInSimulation(unittest.TestCase):
    def test_an_approved_spend_is_carried_out_in_the_simulation(self):
        """Verifies D-053 och FR-20: en utgift över tröskeln väntar, en grundare godkänner, och nästa dag genomförs den en gång."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = load_config(TEST_CONFIG)
        departments = {m.department for m in load_permissions(TEST_CONFIG).roles.values()}
        sc = load_scenario(TEST_CONFIG, "normal", departments, FOUNDERS)
        db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(db.close)
        clock = SimClock(sc.start_date)
        system = build_system(config, db, TEST_CONFIG, clock=clock)
        ensure_org(system.registry, "yorgo")
        sim = Simulation.start(system, config, sc, "yorgo", clock)

        def responder(request):
            state = json.loads(request.messages[-1].content.split("LÄGE (JSON):", 1)[1])
            if state["role"] == "research_lead" and state["day"] == 1:
                return json.dumps({"actions": [{"type": "spend", "initiative": "etsy-mallar", "amount": 12_000,
                                                "purpose": "större annonskampanj", "risk": "low"}]})
            return '{"actions": []}'

        router = ProviderRouter((Slot(RuleProvider("test", responder), 10_000, 10_000_000),), QuotaLedger(db), system.audit)
        cycle = WorkCycle(sim, system, LLMGateway(router, system.engine, system.audit))
        day1 = cycle.day()
        (pending,) = [a for a in day1["actions"] if a["type"] == "spend"]
        self.assertEqual(pending["outcome"], "pending")
        (request,) = system.spend_approvals.pending()
        system.spend_approvals.approve("yorgo", request.approval_id, "ok att testa")
        day2 = cycle.day()
        self.assertEqual([s["outcome"] for s in day2["approved_spends"]], ["done"])
        costs = [e for e in system.ledger.entries() if e.entry_type is EntryType.COST and e.amount_minor == 12_000]
        self.assertEqual(len(costs), 1)
        self.assertIn(f"approval:spend-{request.approval_id}", costs[0].evidence)
        day3 = cycle.day()
        self.assertEqual(day3["approved_spends"], [])


if __name__ == "__main__":
    unittest.main()
