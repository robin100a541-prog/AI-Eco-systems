"""Granskning 2026-10-30 N1/N2: stop-loss gäller före varje utgift, och en nekad utgift raderar inte spärrens läge."""
import tempfile
import unittest
from pathlib import Path

from aie.budget import BudgetBlocked, Risk, SpendRequest
from aie.config import load_config
from aie.ledger import Approval, EntryDraft, EntryType, Status
from aie.memory import Database
from aie.system import build_system

from .fixture_config import TEST_CONFIG


class GatesBeforeSpend(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        self.config = load_config(TEST_CONFIG)
        self.system = build_system(self.config, self.db, TEST_CONFIG)

    def book(self, key, amount, kind, initiative, department="research"):
        self.system.ledger.record("robin", EntryDraft(
            key, department, amount, "SIM", kind, initiative, Approval.APPROVED, ("approval:test",),
            status=Status.SETTLED))

    def test_loss_limit_blocks_next_spend_without_tick_and_trip_survives_refusal(self):
        self.book("cap", self.config.risk.start_capital.amount_minor, EntryType.CAPITAL_IN, "kapital", "finance")
        loss = self.config.risk.max_single_experiment_loss.amount_minor + 100
        self.book("loss", loss, EntryType.COST, "mallar")
        self.assertEqual(self.system.stoploss.active(), ())  # ingen tick() har körts
        request = SpendRequest("research", 100, "SIM", "mallar", Risk.LOW)
        draft = EntryDraft("next", "research", 100, "SIM", EntryType.COST, "mallar", Approval.NOT_REQUIRED,
                           ("file:x",), status=Status.SETTLED)
        with self.assertRaises(BudgetBlocked):
            self.system.budget.record_spend("robin", request, draft)
        self.assertTrue(self.system.stoploss.active())  # utlösningen finns kvar efter den nekade utgiften
        self.assertIn("stoploss.tripped", [e.action for e in self.system.audit.entries()])


if __name__ == "__main__":
    unittest.main()


class AssessmentNeedsEvidence(unittest.TestCase):
    def test_h5_ready_without_simulation_runs_is_refused(self):
        from aie.registry.assessments import evidence_errors

        from .evidence import evidence
        self.assertTrue(evidence_errors({"test": True}))
        self.assertTrue(evidence_errors(evidence() | {"scenarios": {"normal": {"runs": [{}]}}}))
        self.assertEqual(evidence_errors(evidence()), [])
