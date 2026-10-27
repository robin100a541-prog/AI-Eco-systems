"""Tester för Tax Engine (Fas 4f). Verifierar ER-18, ER-19, ER-20, ER-21 och §52."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.budget import BudgetEngine, Risk, SpendRequest, capital_position, load_budgets
from aie.config import ConfigError, load_config
from aie.ledger import Approval, EntryDraft, EntryType, Ledger, Status
from aie.memory import Database
from aie.tax import TaxEngine, TaxError, load_tax_config
from .fixture_config import TEST_CONFIG

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})


def clock_2026():
    return "2026-06-01T12:00:00+00:00"


class TaxCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(TEST_CONFIG)
        self.config = load_tax_config(TEST_CONFIG, FOUNDERS)
        self.limits = load_config(TEST_CONFIG).risk
        self.start()
        for agent_id, role in (("cfo-1", "cfo"), ("cro-1", "cro")):
            self.registry.register(agent_id, role, None, "yorgo", "test")
            for state in (S.CREATED, S.TESTING, S.ACTIVE):
                self.registry.transition(agent_id, state, "yorgo", "test")

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.departments = {m.department for m in self.permissions.roles.values()}
        self.auth = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.ledger = Ledger(self.db, self.auth, self.departments, FOUNDERS, self.audit, approval_threshold=10_000,
                             clock=clock_2026)
        self.tax = TaxEngine(self.db, self.ledger, self.config, self.audit, FOUNDERS, self.auth, clock=clock_2026)

    def book(self, key, entry_type, amount, status=Status.SETTLED):
        return self.ledger.record("robin", EntryDraft(key, "research", amount, "SIM", entry_type, "etsy",
                                                      Approval.NOT_REQUIRED, ("decision:1",), f"ext-{key}",
                                                      status=status))


class TestConfig(TaxCase):
    def test_config_is_validated(self):
        """Verifies ER-18 och D-032: tax.toml kräver alla spår, giltiga satser och andelar som summerar till 100 %."""
        text = (TEST_CONFIG / "tax.toml").read_text(encoding="utf-8")
        for broken in (text.replace("hobby = 3_500", ""), text.replace("yorgo = 5_000", "yorgo = 4_000"),
                       text.replace("untracked_rate = 5_000", "untracked_rate = 1_000"),
                       text.replace("vat_warning_percent = 80", "vat_warning_percent = 100")):
            (self.dir / "tax.toml").write_text(broken, encoding="utf-8")
            with self.subTest(), self.assertRaises(ConfigError):
                load_tax_config(self.dir, FOUNDERS)


class TestTracks(TaxCase):
    def test_every_revenue_gets_a_track_and_owner(self):
        """Verifies ER-18: intäkter märks med spår enligt D-010; spår C delas enligt andelarna, A/B/D har en ägare."""
        sale = self.book("s1", EntryType.REVENUE, 10_000)
        a = self.tax.assign("robin", sale.entry_id, "partnership")
        self.assertEqual((a.track, a.owners), ("partnership", {"robin": 5_000, "yorgo": 5_000}))
        gig = self.book("s2", EntryType.REVENUE, 4_000)
        self.assertEqual(self.tax.assign("cfo-1", gig.entry_id, "self_employment", owner="yorgo").owners,
                         {"yorgo": 10_000})
        cost = self.book("k1", EntryType.COST, 100)
        for args in ((cost.entry_id, "partnership"), (gig.entry_id, "lottery"), (sale.entry_id, "hobby")):
            with self.subTest(args=args), self.assertRaises(TaxError):
                self.tax.assign("robin", *args)  # kostnad, okänt spår, hobby utan ägare
        with self.assertRaises(TaxError):
            self.tax.assign("cro-1", sale.entry_id, "hobby", owner="robin")  # saknar tax.assign

    def test_reassignment_is_a_correction_and_ledger_corrections_inherit(self):
        """Verifies ER-18 och ER-21: byte av spår är en ny rad med motivering; ledgerns rättelser ärver spåret."""
        sale = self.book("s1", EntryType.REVENUE, 10_000)
        first = self.tax.assign("robin", sale.entry_id, "partnership")
        with self.assertRaises(TaxError):
            self.tax.assign("robin", sale.entry_id, "hobby", owner="robin")
        second = self.tax.assign("robin", sale.entry_id, "hobby", owner="robin", note="Skatteverket: saknar vinstsyfte")
        self.assertEqual(second.corrects, first.assignment_id)
        self.assertEqual(len(self.tax.history(sale.entry_id)), 2)
        fix = self.ledger.correct("robin", sale.entry_id, -1_000, "fel pris", ("decision:2",), "fix-1")
        self.assertEqual(self.tax.assignment(fix.entry_id).track, "hobby")
        with self.assertRaises(TaxError):
            self.tax.assign("robin", fix.entry_id, "isk", owner="robin")


class TestReservedTax(TaxCase):
    def test_tax_is_reserved_and_never_disposable(self):
        """Verifies ER-19: beräknad skatt reserveras som åtagande och minskar det disponibla kapitalet."""
        self.ledger.record("robin", EntryDraft("cap", "finance", 1_000_000, "SIM", EntryType.CAPITAL_IN, "start",
                                               Approval.APPROVED, ("decision:start",), status=Status.SETTLED))
        sale = self.book("s1", EntryType.REVENUE, 100_000)
        self.tax.assign("robin", sale.entry_id, "partnership")
        refund = self.book("r1", EntryType.REFUND, 10_000)
        self.tax.assign("robin", refund.entry_id, "partnership")
        self.book("s2", EntryType.REVENUE, 1_001)  # utan spår
        self.book("s3", EntryType.REVENUE, 50_000, status=Status.PENDING)  # väntad: ingen skatt än (ER-11)
        position = self.tax.position()
        self.assertEqual(position.reserved_minor, 90_000 * 4_000 // 10_000 + 501)  # 36 000 + 501 (avrundat uppåt)
        self.assertEqual(len(position.untracked), 1)
        entries = self.ledger.entries("SIM")
        without = capital_position(entries, self.limits)
        with_tax = capital_position(entries, self.limits, position.reserved_minor)
        self.assertEqual(without.disposable_minor - with_tax.disposable_minor, 36_501)
        self.assertEqual(without.reinvestable_minor, 0)
        self.assertEqual(with_tax.reinvestable_minor, (91_001 - 36_501) * 50 // 100)

    def test_budget_engine_blocks_spending_the_tax(self):
        """Verifies ER-19 och §52: budgetmotorn med Tax Engine låter aldrig utgifter äta den reserverade skatten."""
        self.ledger.record("robin", EntryDraft("cap", "finance", 300_000, "SIM", EntryType.CAPITAL_IN, "start",
                                               Approval.APPROVED, ("decision:start",), status=Status.SETTLED))
        sale = self.book("s1", EntryType.REVENUE, 15_000)
        self.tax.assign("robin", sale.entry_id, "partnership")  # likvida 315 000, reserv 300 000, skatt 6 000
        budgets = load_budgets(TEST_CONFIG, self.departments, self.limits)
        request = SpendRequest("research", 9_500, "SIM", "etsy", Risk.LOW)
        self.assertTrue(BudgetEngine(self.ledger, self.limits, budgets, self.audit).check("robin", request).allowed)
        check = BudgetEngine(self.ledger, self.limits, budgets, self.audit, tax=self.tax).check("robin", request)
        self.assertFalse(check.allowed)
        self.assertTrue(any("åtaget 6000" in r for r in check.blocked))


class TestVat(TaxCase):
    def test_warning_at_80_percent_and_block_at_the_limit_until_both_founders_decide(self):
        """Verifies ER-20: varning vid 80 %, ny försäljning blockeras vid gränsen tills båda grundarna har beslutat."""
        self.book("s1", EntryType.REVENUE, 9_600_000)
        self.assertEqual(self.tax.check_vat().level, "warning")
        self.assertIsNone(self.tax.tool_block_reason(None, "sales.create_listing"))
        self.book("s2", EntryType.REVENUE, 2_400_000, status=Status.PENDING)  # väntad försäljning räknas
        self.assertIn("momsgränsen", self.tax.tool_block_reason(None, "sales.create_listing"))
        self.assertIsNone(self.tax.tool_block_reason(None, "report.write"))
        actions = [e.action for e in self.audit.entries() if e.action.startswith("tax.vat_")]
        self.assertEqual(actions, ["tax.vat_warning", "tax.vat_limit"])  # en gång var
        self.tax.vat_vote("robin", 2026, "momsregistrering inlämnad")
        with self.assertRaises(TaxError):
            self.tax.vat_vote("robin", 2026, "igen")
        self.assertIsNotNone(self.tax.tool_block_reason(None, "publish.listing"))
        status = self.tax.vat_vote("yorgo", 2026, "momsregistrering inlämnad")
        self.assertTrue(status.decided)
        self.assertIsNone(self.tax.tool_block_reason(None, "sales.create_listing"))

    def test_authorization_engine_uses_the_vat_gate(self):
        """Verifies ER-20: spärren fungerar i AuthorizationEngine för ett verktyg som rollen annars hade."""
        self.book("s1", EntryType.REVENUE, 12_000_000)
        reason = self.tax.tool_block_reason(self.registry.get("cfo-1"), "payment.request")
        self.assertIn("ER-20", reason)


class TestArchive(TaxCase):
    def test_declaration_basis_per_founder_and_nothing_can_be_deleted(self):
        """Verifies ER-21: underlag per grundare exporteras och loggas; inget underlag kan raderas."""
        sale = self.book("s1", EntryType.REVENUE, 10_000)
        self.tax.assign("robin", sale.entry_id, "partnership")
        own = self.book("s2", EntryType.REVENUE, 3_000)
        self.tax.assign("robin", own.entry_id, "hobby", owner="yorgo")
        self.book("k1", EntryType.COST, 2_000)
        path = self.tax.export("robin", 2026, self.dir / "export")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["archive_until"], 2033)
        self.assertEqual(data["tracks"]["partnership"]["gross_minor"], 5_000)
        self.assertEqual(data["tracks"]["partnership"]["costs_share_minor"], 1_000)
        self.assertNotIn("hobby", data["tracks"])  # yorgos intäkt
        self.assertEqual(self.tax.exports(2026)[0]["file"], path.name)
        for sql in ("DELETE FROM tax_assignments", "UPDATE tax_assignments SET track = 'isk'", "DELETE FROM tax_events",
                    "DELETE FROM ledger_entries"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)
        with self.assertRaises(TaxError):
            self.tax.export("cfo-1", 2026, self.dir / "export")


if __name__ == "__main__":
    unittest.main()
