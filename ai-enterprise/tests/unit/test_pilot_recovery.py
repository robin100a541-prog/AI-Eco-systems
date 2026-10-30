"""Verifies H1–H3/M2, ER-07–09, ER-19–23 and SR-12: recoverable dated imports."""
from unittest.mock import patch

from aie.ledger import EntryType, compute_result
from aie.pilot.live import PilotError, import_sales, parse_sales_csv
from aie.reporting.daily import daily_report
from .test_pilot_live import PilotLive


def export(refunded=False, price="12.00", day="2025-12-31", refund_day="2026-01-02"):
    return ("Purchase ID,Purchase Date,Sale Price ($),Fees ($),Refunded?,Refund Date\n"
            f"X1,{day},{price},1.70,{'true' if refunded else 'false'},{refund_day if refunded else ''}\n")


class Recovery(PilotLive):
    def import_(self, system, text, net=10.30):
        return import_sales(system, "robin", "pilot-f-skatt-guide", text, 10.0, net)

    def test_later_refund_is_a_new_event_and_retry_is_idempotent(self):
        self.prepare_and_approve()
        s = self.system()
        self.import_(s, export())
        update = self.import_(s, export(True), -1.70)
        self.assertEqual((update.sales, update.refunds, update.refunds_minor), (0, 1, 12000))
        self.assertIsNone(update.mismatch)
        repeat = self.import_(s, export(True), -1.70)
        self.assertEqual((repeat.sales, repeat.refunds, repeat.duplicates), (0, 0, 1))
        self.assertEqual(compute_result(s.ledger.entries("SEK"), "SEK").net_minor, -1700)
        self.assertEqual(sum(e.entry_type is EntryType.REFUND for e in s.ledger.entries("SEK")), 1)
        self.assertTrue(s.audit.verify().ok)

    def test_interruption_rolls_back_posts_and_audit_then_retry_recovers(self):
        self.prepare_and_approve()
        s = self.system()
        original = s.ledger.record
        before = tuple(s.audit.entries())
        def fail_fee(actor, draft):
            if draft.entry_type is EntryType.FEE:
                raise RuntimeError("injected interruption")
            return original(actor, draft)
        with patch.object(s.ledger, "record", side_effect=fail_fee):
            with self.assertRaises(RuntimeError):
                self.import_(s, export())
        self.assertFalse(any(e.entry_type is EntryType.REVENUE for e in s.ledger.entries("SEK")))
        self.assertEqual(tuple(s.audit.entries()), before)
        result = self.import_(s, export())
        self.assertEqual((result.sales, result.fees_minor, result.net_minor), (1, 1700, 10300))

    def test_partial_legacy_import_with_event_date_recovers_missing_fee(self):
        self.prepare_and_approve()
        s = self.system()
        original = s.ledger.record
        from aie.ledger import EntryDraft, Approval, Status
        original("robin", EntryDraft("gumroad:X1:sale", "research", 12000, "SEK", EntryType.REVENUE,
            "pilot-f-skatt-guide", Approval.APPROVED, ("decision:1", "external:kurs-usd-sek/10.0"),
            external_id="gumroad:X1:sale", status=Status.SETTLED, occurred_on="2025-12-31"))
        result = self.import_(s, export())
        self.assertEqual((result.sales, result.fees_minor), (0, 1700))
        self.assertEqual(compute_result(s.ledger.entries("SEK"), "SEK").net_minor, 10300)

    def test_event_dates_control_tax_and_reports_without_changing_registration_time(self):
        self.prepare_and_approve()
        s = self.system()
        self.import_(s, export(True), -1.70)
        sale = next(e for e in s.ledger.entries("SEK") if e.entry_type is EntryType.REVENUE)
        refund = next(e for e in s.ledger.entries("SEK") if e.entry_type is EntryType.REFUND)
        self.assertEqual((sale.economic_date, refund.economic_date), ("2025-12-31", "2026-01-02"))
        self.assertNotEqual(sale.recorded_at[:10], sale.economic_date)
        years = {r.year: r.gross_minor for r in s.tax.position("SEK").rows}
        self.assertEqual(years, {2025: 12000, 2026: -12000})
        self.assertIn("2025-12-31", daily_report(s, "2025-12-31").render())
        self.assertGreater(s.tax.vat_status(2025).sales_minor, 0)

    def test_mismatch_retry_reuses_incident(self):
        self.prepare_and_approve()
        s = self.system()
        a = self.import_(s, export(), 50)
        b = self.import_(s, export(), 50)
        self.assertEqual(a.incident_id, b.incident_id)
        self.assertEqual(len(s.incidents.all()), 1)

    def test_changed_financial_data_or_stale_refund_export_is_refused(self):
        self.prepare_and_approve()
        s = self.system()
        self.import_(s, export())
        with self.assertRaises(PilotError):
            self.import_(s, export(price="13.00"))
        self.import_(s, export(True), -1.70)
        with self.assertRaises(PilotError):
            self.import_(s, export())

    def test_ledger_correction_cannot_be_reported_as_reconciled(self):
        self.prepare_and_approve()
        s = self.system()
        self.import_(s, export())
        sale = next(e for e in s.ledger.entries("SEK") if e.entry_type is EntryType.REVENUE)
        s.ledger.correct("robin", sale.entry_id, 100, "test correction", ("file:correction", "decision:1"), "correction")
        with self.assertRaisesRegex(PilotError, "ledgerns netto"):
            self.import_(s, export())

    def test_unknown_refund_date_and_invalid_amounts_fail_before_writes(self):
        for text in (export(True).replace("2026-01-02", ""), export(price="nan"), export(price="1.001"),
                     export() + export(price="13.00").splitlines()[1] + "\n"):
            with self.subTest(text=text), self.assertRaises(PilotError):
                parse_sales_csv(text)

    def test_inner_savepoint_failure_does_not_commit_outer_transaction(self):
        self.prepare_and_approve()
        s = self.system()
        before = tuple(s.audit.entries())
        with self.assertRaises(RuntimeError):
            with s.db.transaction():
                s.audit.append("review-test", "outer.test", {})
                try:
                    with s.db.transaction():
                        s.audit.append("review-test", "inner.test", {})
                        raise ValueError("inner failure")
                except ValueError:
                    pass
                self.assertFalse(any(e.action == "inner.test" for e in s.audit.entries()))
                raise RuntimeError("outer failure")
        self.assertEqual(tuple(s.audit.entries()), before)

    def test_version_33_upgrade_preserves_immutable_legacy_rows(self):
        from aie.memory import Database
        from aie.memory.migrations import MIGRATIONS
        folder = self.dir / "legacy"
        with Database.open(folder, "sim", migrations=MIGRATIONS[:33]) as db:
            with db.transaction() as tx:
                tx.execute("INSERT INTO ledger_entries (idempotency_key, recorded_at, recorded_by, department, "
                           "amount_minor, currency, entry_type, initiative, approval_status, evidence, note) "
                           "VALUES ('old', '2025-12-31T00:00:00+00:00', 'robin', 'research', 100, 'SIM', "
                           "'revenue', 'legacy', 'not_required', '[\"file:legacy\"]', 'old record')")
        with Database.open(folder, "sim") as upgraded:
            self.assertEqual(upgraded.schema_version, len(MIGRATIONS))
            row = upgraded.connection.execute("SELECT amount_minor, occurred_on FROM ledger_entries").fetchone()
            self.assertEqual(row, (100, None))
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):
                upgraded.connection.execute("UPDATE ledger_entries SET occurred_on = '2024-01-01'")
