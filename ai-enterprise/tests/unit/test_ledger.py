"""Tester för src/aie/ledger (Fas 4a). Verifierar §40, ER-01, ER-06–09, ER-11, ER-14–16, ER-23 och SR-12.

HUMAN_APPROVAL_THRESHOLD = 10 000 i testerna, som i repots konfiguration.
"""

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.ledger import (
    Approval,
    DuplicateEntry,
    EntryDraft,
    EntryType,
    Ledger,
    LedgerError,
    Status,
    compute_result,
    recompute,
    result_for,
)
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
T = EntryType


def draft(key="etsy-order-1", amount=10_000, kind=T.REVENUE, **kw):
    base = EntryDraft(
        idempotency_key=key,
        department="research",
        amount_minor=amount,
        currency="SIM",
        entry_type=kind,
        initiative="etsy-mallar",
        approval=Approval.NOT_REQUIRED,
        evidence=("external:etsy/order/1",),
    )
    return replace(base, **kw)


class LedgerCase(unittest.TestCase):
    environment = "sim"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.start()
        for agent_id, role, manager in (
            ("ceo-1", "ceo", None),
            ("cfo-1", "cfo", None),
            ("audit-1", "auditor", None),
            ("lead-1", "research_lead", "ceo-1"),
            ("res-1", "researcher", "lead-1"),
        ):
            self.registry.register(agent_id, role, manager, "yorgo", "test")
            for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                self.registry.transition(agent_id, state, "yorgo", "test")

    def start(self):
        self.db = Database.open(self.dir / "data", self.environment)
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.engine = AuthorizationEngine(
            self.permissions, self.registry, self.environment, self.audit
        )
        departments = {m.department for m in self.permissions.roles.values()}
        self.ledger = Ledger(
            self.db,
            self.engine,
            departments,
            FOUNDERS,
            self.audit,
            approval_threshold=10_000,
            components=frozenset({"system:payments"}),
        )

    def actions(self):
        return [e.action for e in self.audit.entries()]

    def settled(self, d, actor="system:payments"):
        return self.ledger.record(actor, replace(d, status=Status.SETTLED))


class TestRecord(LedgerCase):
    def test_entry_has_all_twelve_fields_and_survives_restart(self):
        """Verifies §40, ER-06: ID, tid, avsändare, departement, belopp+valuta, typ, initiativ, godkännande,
        underlag, externt ID, slutlig status och korrigering finns, och posten finns kvar efter omstart."""
        entry = self.ledger.record("system:payments", draft(external_id="etsy-1"))
        self.db.close()
        self.start()
        e = self.ledger.get(entry.entry_id)
        self.assertEqual(
            (
                e.recorded_by,
                e.department,
                e.amount_minor,
                e.currency,
                e.entry_type,
                e.initiative,
                e.approval,
                e.evidence,
                e.external_id,
                e.status,
                e.corrects,
            ),
            (
                "system:payments",
                "research",
                10_000,
                "SIM",
                T.REVENUE,
                "etsy-mallar",
                Approval.NOT_REQUIRED,
                ("external:etsy/order/1",),
                "etsy-1",
                Status.PENDING,
                None,
            ),
        )
        self.assertTrue(e.recorded_at)
        self.assertIn("ledger.recorded", self.actions())

    def test_amounts_are_exact_integers_with_currency(self):
        """Verifies ER-01: flyttal, bool, 0 och negativa belopp avvisas."""
        for amount in (99.5, True, 0, -1, "100"):
            with (
                self.subTest(amount=amount),
                self.assertRaisesRegex(LedgerError, "belopp"),
            ):
                self.ledger.record("robin", draft(amount=amount))
        for currency in ("sek", "SIMS", ""):
            with self.subTest(currency=currency), self.assertRaises(LedgerError):
                self.ledger.record("robin", draft(currency=currency))

    def test_sim_ledger_accepts_only_sim(self):
        """Verifies ER-15, SR-11: simulerade pengar kan inte blandas med verkliga."""
        with self.assertRaisesRegex(LedgerError, "ER-15"):
            self.ledger.record("robin", draft(currency="SEK"))

    def test_required_fields_and_no_secrets(self):
        """Verifies §40, SR-10: underlag, initiativ och känt departement krävs; hemligheter avvisas."""
        for bad in (
            draft(evidence=()),
            draft(evidence=("bara text",)),
            draft(initiative=" "),
            draft(department="marknad"),
            draft(key=""),
            draft(note="api_key=abc123def456"),
            draft(status=Status.FAILED),
        ):
            with self.subTest(bad=bad), self.assertRaises(LedgerError):
                self.ledger.record("robin", bad)
        self.assertEqual(self.ledger.entries(), ())

    def test_only_founders_and_named_components_write(self):
        """Verifies SR-01: agenter skriver inte i ledgern i Fas 4a; försöket revideras."""
        for actor in ("cfo-1", "ceo-1", "system:other", "mallory"):
            with (
                self.subTest(actor=actor),
                self.assertRaisesRegex(LedgerError, "får inte skriva"),
            ):
                self.ledger.record(actor, draft())
        self.assertEqual(self.actions().count("ledger.denied"), 4)
        self.assertEqual(self.ledger.record("yorgo", draft()).recorded_by, "yorgo")
        with self.assertRaises(LedgerError):
            Ledger(
                self.db,
                self.engine,
                {"research"},
                FOUNDERS,
                self.audit,
                10_000,
                frozenset({"payments"}),
            )


class TestApproval(LedgerCase):
    def test_large_outgoing_amount_must_state_its_approval(self):
        """Verifies ER-14: en kostnad över HUMAN_APPROVAL_THRESHOLD är godkänd (med hänvisning) eller märkt ogodkänd."""
        big = draft(
            key="licens", amount=10_001, kind=T.COST, evidence=("file:offert.pdf",)
        )
        with self.assertRaisesRegex(LedgerError, "ER-14"):
            self.ledger.record("robin", big)
        with self.assertRaisesRegex(LedgerError, "approval: eller decision:"):
            self.ledger.record("robin", replace(big, approval=Approval.APPROVED))
        ok = self.ledger.record(
            "robin",
            replace(
                big,
                approval=Approval.APPROVED,
                evidence=("file:offert.pdf", "approval:3"),
            ),
        )
        self.assertEqual(ok.approval, Approval.APPROVED)
        self.assertEqual(
            self.ledger.record("robin", draft(amount=10_001)).approval,
            Approval.NOT_REQUIRED,
        )

    def test_missing_threshold_means_every_outgoing_amount_states_approval(self):
        """Verifies ER-02: en saknad gräns betyder blockera, aldrig obegränsat."""
        ledger = Ledger(
            self.db,
            self.engine,
            {"research"},
            FOUNDERS,
            self.audit,
            approval_threshold=None,
        )
        with self.assertRaisesRegex(LedgerError, "ER-02"):
            ledger.record("robin", draft(amount=1, kind=T.FEE))

    def test_unapproved_fact_is_recorded_and_flagged(self):
        """Verifies §23, ER-14: en kostnad som redan skett göms aldrig; den registreras och syns som avvikelse."""
        e = self.settled(
            draft(
                key="oväntad", amount=20_000, kind=T.COST, approval=Approval.UNAPPROVED
            )
        )
        result = compute_result(self.ledger.entries(), "SIM")
        self.assertEqual(result.unapproved, (e.entry_id,))
        self.assertEqual(result.costs_minor, 20_000)


class TestDuplicates(LedgerCase):
    def test_same_key_same_content_is_idempotent(self):
        """Verifies SR-12, ER-07: ett omförsök med samma idempotensnyckel ger samma post, inte en till."""
        first = self.ledger.record("system:payments", draft())
        again = self.ledger.record("system:payments", draft())
        self.assertEqual(first.entry_id, again.entry_id)
        self.assertEqual(len(self.ledger.entries()), 1)
        self.assertIn("ledger.replayed", self.actions())

    def test_same_key_other_content_or_same_external_id_is_refused(self):
        """Verifies ER-07 (ROADMAP-nyckeltest): samma externa ID två gånger → avvisas."""
        self.ledger.record("system:payments", draft(external_id="etsy-1"))
        with self.assertRaises(DuplicateEntry) as caught:
            self.ledger.record(
                "system:payments", draft(amount=9_999, external_id="etsy-1")
            )
        self.assertEqual(caught.exception.existing_entry_id, 1)
        with self.assertRaisesRegex(DuplicateEntry, "externt ID"):
            self.ledger.record(
                "system:payments", draft(key="annan-nyckel", external_id="etsy-1")
            )
        self.assertEqual(len(self.ledger.entries()), 1)
        self.assertEqual(self.actions().count("ledger.duplicate_refused"), 2)

    def test_database_is_the_last_barrier(self):
        """Verifies ER-07: även förbi koden stoppar databasen en dubblett."""
        self.ledger.record("system:payments", draft(external_id="etsy-1"))
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO ledger_entries (idempotency_key, recorded_at, recorded_by, department, "
                "amount_minor, currency, entry_type, initiative, approval_status, evidence, external_id, note) "
                "VALUES ('x', 't', 'a', 'research', 1, 'SIM', 'revenue', 'i', 'not_required', '[\"url:x\"]', "
                "'etsy-1', '')"
            )


class TestHistoryIsNeverRewritten(LedgerCase):
    def test_entries_and_status_cannot_be_updated_or_deleted(self):
        """Verifies ER-08: databasen vägrar UPDATE och DELETE på poster och statushändelser."""
        self.ledger.record("system:payments", draft())
        for sql in (
            "UPDATE ledger_entries SET amount_minor = 1",
            "DELETE FROM ledger_entries",
            "UPDATE ledger_status SET status = 'settled'",
            "DELETE FROM ledger_status",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as tx:
                tx.execute(sql)

    def test_status_only_moves_forward(self):
        """Verifies §40: pending → settled; en slutlig status ändras aldrig, varken i koden eller i databasen."""
        e = self.ledger.record("system:payments", draft())
        settled = self.ledger.set_status(
            "system:payments", e.entry_id, Status.SETTLED, "Etsy betalade ut"
        )
        self.assertEqual(
            [h.status for h in settled.history], [Status.PENDING, Status.SETTLED]
        )
        with self.assertRaisesRegex(LedgerError, "korrigeringspost"):
            self.ledger.set_status("robin", e.entry_id, Status.CANCELLED, "ångrar")
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO ledger_status (entry_id, status, actor, note, at) VALUES (?, 'failed', 'x', 'x', 't')",
                (e.entry_id,),
            )
        with self.assertRaises(LedgerError):
            self.ledger.set_status("robin", e.entry_id, Status.PENDING, "tillbaka")

    def test_correction_entry_keeps_the_original(self):
        """Verifies ER-08: ett fel rättas med en spårbar korrigeringspost; originalet är oförändrat."""
        e = self.settled(draft(amount=10_000))
        fix = self.ledger.correct(
            "robin",
            e.entry_id,
            -1_000,
            "Fel belopp i importen",
            ("file:etsy-rapport.csv",),
            "fix-1",
        )
        self.assertEqual(
            (fix.corrects, fix.amount_minor, fix.entry_type, fix.status),
            (e.entry_id, -1_000, T.REVENUE, Status.SETTLED),
        )
        self.assertEqual(self.ledger.get(e.entry_id).amount_minor, 10_000)
        self.assertEqual(
            self.ledger.correct(
                "robin",
                e.entry_id,
                -1_000,
                "Fel belopp i importen",
                ("file:etsy-rapport.csv",),
                "fix-1",
            ).entry_id,
            fix.entry_id,
        )
        self.assertEqual(
            compute_result(self.ledger.entries(), "SIM").revenue_minor, 9_000
        )
        self.assertIn("ledger.corrected", self.actions())

    def test_bad_corrections_are_refused(self):
        """Verifies ER-08: väntande poster avbryts i stället; en post kan inte bli negativ; korrigeringar rättas inte."""
        pending = self.ledger.record("robin", draft(key="p"))
        with self.assertRaisesRegex(LedgerError, "cancelled"):
            self.ledger.correct("robin", pending.entry_id, -1, "x", ("url:x",), "c1")
        e = self.settled(draft(key="s", amount=500))
        with self.assertRaisesRegex(LedgerError, "negativ"):
            self.ledger.correct(
                "robin", e.entry_id, -501, "för mycket", ("url:x",), "c2"
            )
        fix = self.ledger.correct("robin", e.entry_id, -100, "rätt", ("url:x",), "c3")
        with self.assertRaisesRegex(LedgerError, "originalposten"):
            self.ledger.correct("robin", fix.entry_id, -1, "x", ("url:x",), "c4")
        for amount in (0, 1.5):
            with self.assertRaises(LedgerError):
                self.ledger.correct("robin", e.entry_id, amount, "x", ("url:x",), "c5")


class TestResult(LedgerCase):
    def book(self):
        self.settled(draft(key="r1", amount=10_000))
        self.settled(
            draft(key="f1", amount=1_000, kind=T.FEE, evidence=("external:etsy/fee/1",))
        )
        self.settled(
            draft(key="c1", amount=3_000, kind=T.COST, evidence=("file:kvitto.pdf",))
        )
        self.settled(draft(key="b1", amount=500, kind=T.REFUND))
        self.settled(
            draft(
                key="k1",
                amount=50_000,
                kind=T.CAPITAL_IN,
                approval=Approval.APPROVED,
                evidence=("decision:1",),
            )
        )
        failed = self.ledger.record("system:payments", draft(key="r2", amount=7_000))
        self.ledger.set_status(
            "system:payments", failed.entry_id, Status.FAILED, "kortet nekades"
        )

    def test_net_profit_only_from_settled_entries(self):
        """Verifies ER-09 (§52 nettovinst från registrerade poster): intäkt − återbetalning − kostnad − avgift."""
        self.book()
        r = compute_result(self.ledger.entries(), "SIM")
        self.assertEqual(
            (
                r.revenue_minor,
                r.refunds_minor,
                r.costs_minor,
                r.fees_minor,
                r.net_minor,
            ),
            (10_000, 500, 3_000, 1_000, 5_500),
        )
        self.assertFalse(r.preliminary, r.reasons)
        self.assertEqual(len(r.entry_ids), 4)  # kapital och misslyckade räknas inte

    def test_forecast_is_not_profit_and_result_is_preliminary(self):
        """Verifies ER-11: en väntad betalning är ingen intäkt, och resultatet märks preliminärt."""
        self.book()
        self.ledger.record("system:payments", draft(key="r3", amount=99_000))
        r = compute_result(self.ledger.entries(), "SIM")
        self.assertEqual(r.net_minor, 5_500)
        self.assertTrue(r.preliminary)
        self.assertIn("1 poster väntar fortfarande", r.reasons)
        self.assertIn("PRELIMINÄRT", r.describe())

    def test_revenue_without_any_costs_is_preliminary(self):
        """Verifies ER-11: när kostnader saknas för ett initiativ är resultatet preliminärt."""
        self.settled(draft(key="r1", amount=10_000, initiative="gumroad"))
        r = compute_result(self.ledger.entries(), "SIM", initiative="gumroad")
        self.assertEqual(
            (r.net_minor, r.preliminary, r.reasons),
            (10_000, True, ("kostnader saknas för gumroad",)),
        )

    def test_scope_by_initiative_and_department(self):
        self.book()
        self.settled(
            draft(key="x1", amount=2_000, initiative="gumroad", department="finance")
        )
        self.assertEqual(
            compute_result(
                self.ledger.entries(), "SIM", initiative="etsy-mallar"
            ).net_minor,
            5_500,
        )
        self.assertEqual(
            compute_result(
                self.ledger.entries(), "SIM", department="finance"
            ).revenue_minor,
            2_000,
        )

    def test_only_readers_get_results(self):
        """Verifies SR-01: CFO och grundare läser; en forskare utan `ledger.read` nekas och det loggas."""
        self.book()
        self.assertEqual(result_for(self.ledger, "cfo-1", "SIM").net_minor, 5_500)
        self.assertEqual(result_for(self.ledger, "robin", "SIM").net_minor, 5_500)
        with self.assertRaises(PermissionDenied):
            result_for(self.ledger, "res-1", "SIM")

    def test_audit_recomputes_from_the_ledger(self):
        """Verifies ER-16 (§52 rapporter kan granskas mot underlaget): Audit räknar om och hittar en ändrad siffra."""
        self.book()
        report = result_for(self.ledger, "cfo-1", "SIM")
        self.assertEqual(
            recompute(self.db, self.engine, FOUNDERS, "audit-1", report), ()
        )
        tampered = replace(
            report, net_minor=report.net_minor + 1_000, costs_minor=2_000
        )
        found = recompute(self.db, self.engine, FOUNDERS, "audit-1", tampered)
        self.assertEqual(len(found), 2)
        self.assertIn("nettovinst: rapporterat 6500, ledgern visar 5500", found)
        with self.assertRaises(
            PermissionDenied
        ):  # CFO granskar inte sin egen rapport (§18)
            recompute(self.db, self.engine, FOUNDERS, "cfo-1", report)


class TestProd(LedgerCase):
    environment = "prod"

    def test_prod_never_takes_sim_and_never_mixes_currencies(self):
        """Verifies ER-15: SIM avvisas i prod, och en beräkning tar bara en valuta."""
        with self.assertRaisesRegex(LedgerError, "aldrig registreras i prod"):
            self.ledger.record("robin", draft())
        self.settled(draft(key="sek", currency="SEK", amount=10_000), actor="robin")
        self.settled(draft(key="eur", currency="EUR", amount=900), actor="robin")
        self.settled(
            draft(key="fee", currency="SEK", amount=100, kind=T.FEE), actor="robin"
        )
        self.assertEqual(compute_result(self.ledger.entries(), "SEK").net_minor, 9_900)
        self.assertEqual(
            compute_result(self.ledger.entries(), "EUR").revenue_minor, 900
        )


if __name__ == "__main__":
    unittest.main()
