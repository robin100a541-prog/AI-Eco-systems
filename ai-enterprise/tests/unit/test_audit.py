"""Tester för src/aie/audit (Fas 1.5). Verifierar SR-09 (append-only, manipulering syns) och SR-10."""
import sqlite3
import tempfile
import unittest
from itertools import count
from pathlib import Path

from aie.audit import GENESIS_HASH, AuditLog
from aie.audit.log import _canonical, _compute_hash
from aie.memory import Database


class AuditTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        ticks = count()
        self.clock = lambda: f"2026-10-23T12:00:{next(ticks):02d}+00:00"  # förutsägbar tid
        self.db = self.reopen()

    def reopen(self):
        if getattr(self, "db", None):
            self.db.close()
        db = Database.open(self.data_dir, "sim")
        self.addCleanup(db.close)
        self.db = db
        self.log = AuditLog(db, clock=self.clock)
        return db

    def fill(self, n=3):
        return [self.log.append("cli", f"event.{i}", {"i": i, "belopp": 100 * i}) for i in range(1, n + 1)]

    def tamper(self, sql, params=()):
        """Simulerar någon med direkt åtkomst till filen: går förbi triggers och ändrar ändå."""
        self.db.connection.execute("DROP TRIGGER audit_log_no_update")
        self.db.connection.execute("DROP TRIGGER audit_log_no_delete")
        self.db.connection.execute(sql, params)


class TestAppend(AuditTestCase):
    def test_chain_links_each_row_to_previous(self):
        """Verifies SR-09: rad 1 pekar på genesis, varje följande rad på föregående rads hash."""
        first, second, third = self.fill()
        self.assertEqual(first.prev_hash, GENESIS_HASH)
        self.assertEqual(second.prev_hash, first.hash)
        self.assertEqual(third.prev_hash, second.hash)
        self.assertEqual([e.seq for e in self.log.entries()], [1, 2, 3])

    def test_entries_round_trip(self):
        """Verifies SR-09: det som läses tillbaka är exakt det som skrevs."""
        written = self.log.append("agent:cfo", "budget.checked", {"belopp": 500, "valuta": "SIM", "ok": True})
        (read,) = self.log.entries()
        self.assertEqual(read, written)

    def test_valid_chain_verifies(self):
        """Verifies SR-09: en orörd kedja godkänns och head_hash är sista radens hash."""
        entries = self.fill(5)
        result = self.log.verify()
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.checked, 5)
        self.assertEqual(result.head_hash, entries[-1].hash)

    def test_empty_log_verifies(self):
        """Verifies SR-09: en tom logg är giltig."""
        self.assertEqual(self.log.verify().head_hash, GENESIS_HASH)

    def test_chain_survives_restart(self):
        """Verifies FR-03 och SR-09: kedjan fortsätter korrekt efter omstart."""
        before = self.fill(2)
        self.reopen()
        after = self.log.append("cli", "efter.omstart")
        self.assertEqual(after.seq, 3)
        self.assertEqual(after.prev_hash, before[-1].hash)
        self.assertTrue(self.log.verify().ok)

    def test_secret_keys_never_written(self):
        """Verifies SR-10: hemliga nycklar avvisas innan något skrivs, även i nästlade fält."""
        for details in ({"GROQ_API_KEY": "x"}, {"provider": {"token": "x"}}, {"lista": [{"password": "x"}]}):
            with self.subTest(details=details), self.assertRaises(ValueError):
                self.log.append("cli", "försök", details)
        self.assertEqual(list(self.log.entries()), [])

    def test_unserializable_details_rejected_before_write(self):
        """Verifies SR-09: data som inte kan hashas deterministiskt avvisas utan att kedjan påverkas."""
        with self.assertRaises(TypeError):
            self.log.append("cli", "fel", {"objekt": object()})
        with self.assertRaises(ValueError):
            self.log.append("cli", "fel", {"tal": float("nan")})
        self.assertEqual(self.log.append("cli", "ok").seq, 1)

    def test_actor_and_action_required(self):
        """Verifies SR-09: varje rad har källa och händelse."""
        with self.assertRaises(ValueError):
            self.log.append("", "x")
        with self.assertRaises(ValueError):
            self.log.append("cli", "")


class TestAppendOnly(AuditTestCase):
    def test_update_blocked_by_database(self):
        """Verifies SR-09: SQLite vägrar ändra en rad i audit_log."""
        self.fill(1)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.db.connection.execute("UPDATE audit_log SET action = 'ändrad'")
        self.assertIn("append-only", str(ctx.exception))

    def test_delete_blocked_by_database(self):
        """Verifies SR-09: SQLite vägrar radera en rad i audit_log."""
        self.fill(1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute("DELETE FROM audit_log")


class TestTamperDetection(AuditTestCase):
    def test_changed_details_detected(self):
        """Verifies SR-09: ett ändrat belopp i en rad upptäcks på exakt den raden."""
        self.fill(3)
        self.tamper("UPDATE audit_log SET details = '{\"belopp\":1,\"i\":2}' WHERE seq = 2")
        result = self.log.verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, 2)
        self.assertIn("har ändrats", result.reason)
        self.assertEqual(result.checked, 1)

    def test_rewritten_row_with_new_hash_breaks_next_link(self):
        """Verifies SR-09: även om hashen räknas om för en ändrad rad bryts länken till nästa rad."""
        entries = self.fill(3)
        forged = entries[1]
        new_details = {"i": 2, "belopp": 999_999}
        new_hash = _compute_hash(forged.seq, forged.timestamp, forged.actor, forged.action, new_details, forged.prev_hash)
        self.tamper("UPDATE audit_log SET details = ?, hash = ? WHERE seq = 2", (_canonical(new_details), new_hash))
        result = self.log.verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, 3)
        self.assertIn("prev_hash", result.reason)

    def test_deleted_middle_row_detected(self):
        """Verifies SR-09: en raderad rad mitt i kedjan upptäcks."""
        self.fill(4)
        self.tamper("DELETE FROM audit_log WHERE seq = 2")
        result = self.log.verify()
        self.assertFalse(result.ok)
        self.assertIn("rad 2 saknas", result.reason)

    def test_truncation_changes_head_hash(self):
        """Verifies SR-09: borttagna sista rader ger en annan head_hash än den som sparats tidigare.

        Kedjan i sig är fortfarande giltig (känd begränsning), men en extern kopia av
        head_hash avslöjar trunkeringen.
        """
        self.fill(3)
        saved_head = self.log.verify().head_hash
        self.tamper("DELETE FROM audit_log WHERE seq = 3")
        result = self.log.verify()
        self.assertTrue(result.ok)
        self.assertNotEqual(result.head_hash, saved_head)

    def test_corrupt_json_detected(self):
        """Verifies SR-09: trasig JSON i en rad ger ett tydligt fel, inte en krasch."""
        self.fill(2)
        self.tamper("UPDATE audit_log SET details = '{trasig' WHERE seq = 2")
        result = self.log.verify()
        self.assertFalse(result.ok)
        self.assertIn("inte giltig JSON", result.reason)


if __name__ == "__main__":
    unittest.main()
