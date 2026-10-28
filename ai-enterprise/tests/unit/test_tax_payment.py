"""Tester för betald skatt och skatteunderlag (F3+F4, D-052). Verifierar D-052, ER-19, ER-21, ER-08, ER-15 och FR-03."""
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, capital_position, load_budgets
from aie.config import ConfigError, load_config
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.memory.migrations import MIGRATIONS
from aie.tax import TaxEngine, TaxError, load_tax_config

from .fixture_config import TEST_CONFIG

FOUNDERS = frozenset({"robin", "yorgo"})


class Clock:
    day = "2027-06-01"

    def __call__(self):
        return f"{self.day}T12:00:00+00:00"


class PaymentCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.clock = Clock()
        self.limits = load_config(TEST_CONFIG).risk
        self.open(load_tax_config(TEST_CONFIG, FOUNDERS))

    def open(self, tax_config):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        permissions = load_permissions(TEST_CONFIG)
        self.departments = {m.department for m in permissions.roles.values()}
        self.audit = AuditLog(self.db)
        auth = AuthorizationEngine(permissions, AgentRegistry(permissions, self.db), "sim", self.audit)
        self.ledger = Ledger(self.db, auth, self.departments, FOUNDERS, self.audit, 10_000, clock=self.clock)
        self.tax = TaxEngine(self.db, self.ledger, tax_config, self.audit, FOUNDERS, auth, clock=self.clock)
        self.n = 0

    def book(self, kind, amount, initiative="etsy", department="research"):
        self.n += 1
        approval, evidence = ((Approval.APPROVED, ("decision:test",)) if amount > 10_000
                              else (Approval.NOT_REQUIRED, ("file:kvitto.pdf",)))
        return self.ledger.record("robin", EntryDraft(f"k{self.n}", department, amount, "SIM", kind, initiative,
                                                      approval, evidence, status=Status.SETTLED))

    def liquid(self):
        return capital_position(self.ledger.entries("SIM"), self.limits).liquid_minor


class TestPayment(PaymentCase):
    def test_paying_all_tax_brings_the_reserve_to_zero_and_cash_drops_once(self):
        """Verifies D-052 och ER-19: när hela skatten är betald är avsättningen noll, och kassan minskar en gång."""
        self.book(EntryType.CAPITAL_IN, 100_000, "start", "finance")
        sale = self.book(EntryType.REVENUE, 10_000)
        self.tax.assign("robin", sale.entry_id, "partnership")
        self.assertEqual(self.tax.reserved_minor(), 4_000)  # 40 % av 10 000
        before = self.liquid()
        self.tax.pay("robin", "partnership", 2027, 4_000, ("file:skattekonto-2027.pdf",))
        self.assertEqual((self.tax.reserved_minor(), self.tax.liability_minor()), (0, 4_000))
        self.assertEqual(before - self.liquid(), 4_000)
        payments = [e for e in self.ledger.entries() if e.entry_type is EntryType.TAX_PAYMENT]
        self.assertEqual(len(payments), 1)
        self.assertEqual(capital_position(self.ledger.entries("SIM"), self.limits, 0).committed_minor, 0)

    def test_years_and_tracks_are_never_mixed(self):
        """Verifies D-052: en betalning för ett spår och år minskar bara den avsättningen."""
        a = self.book(EntryType.REVENUE, 10_000)
        self.tax.assign("robin", a.entry_id, "partnership")  # 4 000 för 2027
        self.clock.day = "2028-03-01"
        b = self.book(EntryType.REVENUE, 10_000)
        self.tax.assign("robin", b.entry_id, "hobby", owner="yorgo")  # 3 500 för 2028
        self.tax.pay("robin", "partnership", 2027, 4_000, ("file:kvitto.pdf",))
        rows = {(r.track, r.year): r.reserved_minor for r in self.tax.position().rows}
        self.assertEqual(rows, {("partnership", 2027): 0, ("hobby", 2028): 3_500})
        self.tax.pay("robin", "partnership", 2028, 1_000, ("file:kvitto.pdf",))  # fel år: minskar inget annat
        self.assertEqual(self.tax.reserved_minor(), 3_500)

    def test_overpayment_never_makes_the_reserve_negative(self):
        """Verifies D-052: en större betalning än avsättningen ger avsättningen noll, aldrig negativ."""
        sale = self.book(EntryType.REVENUE, 10_000)
        self.tax.assign("robin", sale.entry_id, "partnership")
        self.tax.pay("robin", "partnership", 2027, 9_000, ("file:kvitto.pdf",))
        self.assertEqual(self.tax.reserved_minor(), 0)

    def test_only_founders_with_evidence_and_nothing_can_be_rewritten(self):
        """Verifies D-052, ER-08 och ER-21: bara grundare betalar, med underlag; betalningar ändras eller raderas aldrig."""
        for args in (("cfo-1", "partnership", 2027, 1_000, ("file:x",)),
                     ("robin", "lotteri", 2027, 1_000, ("file:x",)),
                     ("robin", "partnership", 27, 1_000, ("file:x",)),
                     ("robin", "partnership", 2027, 0, ("file:x",)),
                     ("robin", "partnership", 2027, 1_000, ())):
            with self.subTest(args=args), self.assertRaises(TaxError):
                self.tax.pay(*args)
        self.tax.pay("robin", "partnership", 2027, 1_000, ("file:kvitto.pdf",))
        for sql in ("UPDATE tax_payments SET year = 2026", "DELETE FROM tax_payments",
                    "DELETE FROM ledger_entries", "UPDATE ledger_entries SET amount_minor = 1"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)

    def test_paying_tax_does_not_change_the_department_base(self):
        """Verifies D-051 och D-052: en betalning minskar kassan och skulden lika mycket, så basen står still."""
        budgets_text = ('config_version = 1\nmode = "capital"\n[departments.research]\nshare = 40\n'
                        'max_commitment = 50_000\nrisk_room = "medium"\npurpose = "försök"\n')
        (self.dir / "budgets.toml").write_text(budgets_text, encoding="utf-8")
        engine = BudgetEngine(self.ledger, self.limits, load_budgets(self.dir, self.departments, self.limits),
                              self.audit, tax=self.tax)
        self.book(EntryType.CAPITAL_IN, 400_000, "start", "finance")
        sale = self.book(EntryType.REVENUE, 20_000)
        self.tax.assign("robin", sale.entry_id, "partnership")
        before = engine.capital_base()
        self.tax.pay("robin", "partnership", 2027, 8_000, ("file:kvitto.pdf",))
        self.assertEqual(engine.capital_base(), before)


class TestBasis(PaymentCase):
    def test_revenue_is_the_default_and_unknown_bases_are_refused(self):
        """Verifies D-052: standardunderlaget är bruttointäkt; ett okänt underlag avvisas."""
        self.assertEqual(load_tax_config(TEST_CONFIG, FOUNDERS).basis, "revenue")
        text = (TEST_CONFIG / "tax.toml").read_text(encoding="utf-8").replace('basis = "revenue"', 'basis = "cash"')
        (self.dir / "tax.toml").write_text(text, encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_tax_config(self.dir, FOUNDERS)

    def test_profit_basis_subtracts_fees_and_costs(self):
        """Verifies D-052: med basis = profit är underlaget intäkter minus återbetalningar, avgifter och kostnader."""
        self.db.close()
        self.dir = self.dir / "profit"
        self.open(replace(load_tax_config(TEST_CONFIG, FOUNDERS), basis="profit"))
        sale = self.book(EntryType.REVENUE, 10_000)
        self.tax.assign("robin", sale.entry_id, "partnership")
        self.book(EntryType.FEE, 2_000)
        self.book(EntryType.COST, 1_000)
        self.book(EntryType.COST, 5_000, initiative="annat")  # inget spår: minskar inget underlag
        (row,) = self.tax.position().rows
        self.assertEqual((row.gross_minor, row.liability_minor), (7_000, 2_800))


class TestMigration(unittest.TestCase):
    def test_existing_ledger_survives_migration_27(self):
        """Verifies FR-03 och ER-08: en ledger från schemaversion 26 uppgraderas utan att något ändras eller försvinner."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Database.open(Path(tmp.name) / "data", "sim", MIGRATIONS[:26])
        with db.transaction() as tx:
            tx.execute("INSERT INTO ledger_entries VALUES (1, 'k1', '2027-01-01', 'robin', 'research', 100, 'SIM', "
                       "'revenue', 'x', 'not_required', '[\"file:a\"]', 'ext-1', NULL, '')")
            tx.execute("INSERT INTO ledger_entries VALUES (2, 'k2', '2027-01-02', 'robin', 'research', -10, 'SIM', "
                       "'revenue', 'x', 'not_required', '[\"file:a\"]', NULL, 1, 'rättelse')")
            tx.execute("INSERT INTO ledger_status (entry_id, status, actor, note, at) VALUES (1, 'settled', 'robin', '', 'x')")
            tx.execute("INSERT INTO tax_assignments (entry_id, track, owners, actor, note, corrects, at) "
                       "VALUES (1, 'partnership', '{}', 'robin', '', NULL, 'x')")
        before = db.connection.execute("SELECT * FROM ledger_entries ORDER BY entry_id").fetchall()
        db.close()
        db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(db.close)
        c = db.connection
        self.assertEqual(db.schema_version, len(MIGRATIONS))
        self.assertEqual(c.execute("SELECT * FROM ledger_entries ORDER BY entry_id").fetchall(), before)
        self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        for sql in ("UPDATE ledger_entries SET note = 'x'", "DELETE FROM ledger_entries",
                    "INSERT INTO ledger_status (entry_id, status, actor, note, at) VALUES (99, 'settled', 'r', '', 'x')"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                c.execute(sql)


if __name__ == "__main__":
    unittest.main()
