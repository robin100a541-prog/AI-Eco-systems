"""Verifies H4/M1, ER-03/05/12/14, SR-12: serialized spending and bound approvals."""
import threading
from dataclasses import replace
from unittest.mock import patch

from aie.audit import AuditLog
from aie.budget import BudgetBlocked, BudgetEngine, Risk, SpendRequest
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, LedgerError, Status
from aie.memory import Database
from .test_budget import BudgetCase, FOUNDERS, spend
from .test_spend_approvals import ApprovalCase


def draft(key, amount=5_000, initiative="etsy"):
    return EntryDraft(key, "research", amount, "SIM", EntryType.COST, initiative,
                      Approval.NOT_REQUIRED, ("file:invoice",), status=Status.SETTLED)


class ConcurrentSpending(BudgetCase):
    def test_two_connections_cannot_spend_the_same_remaining_budget(self):
        for _ in range(9):
            self.book(5_000)
        barrier, results, errors = threading.Barrier(2), [], []
        def attempt(index):
            try:
                with Database.open(self.dir / "data", "sim") as db:
                    audit = AuditLog(db)
                    ledger = Ledger(db, None, self.departments, FOUNDERS, audit, 10_000)
                    engine = BudgetEngine(ledger, self.limits, self.budgets, audit)
                    barrier.wait(timeout=10)
                    try:
                        engine.record_spend("robin", spend(), draft(f"race-{index}", initiative="etsy-mallar"))
                        results.append(True)
                    except BudgetBlocked:
                        results.append(False)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=attempt, args=(n,)) for n in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=20)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.engine.usage("research")[0], 50_000)

    def test_replaying_same_spend_does_not_repeat_the_action(self):
        request = spend()
        d = draft("one", initiative="etsy-mallar")
        a = self.engine.record_spend("robin", request, d)
        b = self.engine.record_spend("robin", request, d)
        self.assertEqual(a.entry_id, b.entry_id)
        self.assertEqual(self.engine.usage("research")[0], 5_000)
        with self.assertRaises(LedgerError):
            self.engine.record_spend("robin", request, replace(d, amount_minor=6_000))


class AtomicApproval(ApprovalCase):
    def test_record_failure_rolls_back_approval_consumption(self):
        aid = self.approved()
        request = SpendRequest("research", 5_000, "SIM", "etsy", Risk.LOW)
        with patch.object(self.ledger, "record", side_effect=RuntimeError("failed write")):
            with self.assertRaises(RuntimeError):
                self.engine.record_spend("lead-1", request, draft("fail"), writer="robin", approval_id=aid)
        self.assertEqual(self.approvals.get(aid).status, "approved")
        a = self.engine.record_spend("lead-1", request, draft("retry"), writer="robin", approval_id=aid)
        self.assertEqual(self.approvals.get(aid).status, "consumed")
        b = self.engine.record_spend("lead-1", request, draft("retry"), writer="robin", approval_id=aid)
        self.assertEqual(a.entry_id, b.entry_id)

    def test_original_risk_and_category_cannot_be_downgraded(self):
        a = self.approvals.request("lead-1", "research", "etsy", 5_000, "SIM", "review",
                                   risk_class=Risk.MEDIUM, category="EXPERIMENT")
        self.approvals.approve("robin", a.approval_id, "ok")
        request = SpendRequest("research", 5_000, "SIM", "etsy", Risk.LOW)
        with self.assertRaises(BudgetBlocked):
            self.engine.record_spend("lead-1", request, draft("downgrade"), writer="robin", approval_id=a.approval_id)
        request = replace(request, risk_class=Risk.MEDIUM, category="EXPERIMENT")
        lower = dict(self.budgets)
        lower["research"] = replace(lower["research"], risk_room=Risk.LOW)
        engine = BudgetEngine(self.ledger, self.limits, lower, self.audit, clock=lambda: self.clock.now,
                              approvals=self.approvals)
        with self.assertRaises(BudgetBlocked):
            engine.record_spend("lead-1", request, draft("lower-room"), writer="robin", approval_id=a.approval_id)
        self.assertEqual(self.approvals.get(a.approval_id).status, "approved")
