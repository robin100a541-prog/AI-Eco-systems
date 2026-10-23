"""Tester för src/aie/audit (Fas 1.5): hashkedjad, append-only revisionslogg.

Verifierar SR-09 (append-only, manipulering upptäcks), FR-03 (överlever omstart) och
SR-10 (inga hemligheter i revisionsloggen). Manipulering simuleras genom att först ta bort
triggrarna, precis som någon med direkt tillgång till databasfilen skulle göra.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.audit import GENESIS_HASH, AuditLog
from aie.memory import Database


class AuditTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        self.db = self.open()
        self.audit = AuditLog(self.db)

    def open(self):
        db = Database.open(self.data_dir, "sim")
        self.addCleanup(db.close)  # Windows låser filen tills den stängs
        return db

    def fill(self, n=4):
        for i in range(1, n + 1):
            self.audit.append("system", f"händelse-{i}", {"nummer": i})

    def tamper(self, sql, params=()):
        """Ändrar tabellen förbi triggrarna, som en angripare med filåtkomst skulle göra."""
        with self.db.transaction() as tx:
            tx.execute("DROP TRIGGER audit_log_no_update")
            tx.execute("DROP TRIGGER audit_log_no_delete")
            tx.execute(sql, params)


class TestChain(AuditTestCase):
    def test_entries_are_chained_from_genesis(self):
        """Verifies SR-09: rad 1 bygger på genesis-hashen och varje rad på föregående rads hash."""
        self.fill(3)
        entries = self.audit.entries()
        self.assertEqual([e.seq for e in entries], [1, 2, 3])
        self.assertEqual(entries[0].prev_hash, GENESIS_HASH)
        self.assertEqual(entries[1].prev_hash, entries[0].hash)
        self.assertEqual(entries[2].prev_hash, entries[1].hash)
        self.assertEqual(self.audit.verify(), [])

    def test_empty_log_is_intact(self):
        """Verifies SR-09: en tom revisionslogg räknas som intakt."""
        self.assertEqual(self.audit.verify(), [])

    def test_survives_restart(self):
        """Verifies FR-03, SR-09: raderna och kedjan finns kvar efter stängning och ny öppning."""
        self.fill(3)
        self.db.close()
        reopened = AuditLog(self.open())
        self.assertEqual(
            [e.action for e in reopened.entries()],
            ["händelse-1", "händelse-2", "händelse-3"],
        )
        self.assertEqual(reopened.verify(), [])
        self.assertEqual(reopened.append("system", "efter omstart").seq, 4)
        self.assertEqual(reopened.verify(), [])

    def test_secrets_in_details_are_masked(self):
        """Verifies SR-10: hemliga nycklar i detaljerna sparas aldrig i klartext."""
        entry = self.audit.append(
            "system", "konfig", {"provider": "groq", "api_key": "gsk_hemlig"}
        )
        self.assertEqual(entry.details, {"provider": "groq", "api_key": "***"})
        stored = self.db.connection.execute("SELECT details FROM audit_log").fetchone()[
            0
        ]
        self.assertNotIn("gsk_hemlig", stored)

    def test_actor_and_action_required(self):
        """Verifies SR-09: en revisionsrad utan aktör eller handling avvisas."""
        with self.assertRaises(ValueError):
            self.audit.append("", "start")
        with self.assertRaises(ValueError):
            self.audit.append("system", "")
        self.assertEqual(self.audit.entries(), [])

    def test_record_rolls_back_with_surrounding_transaction(self):
        """Verifies SR-09, FR-03: en revisionsrad i en transaktion som misslyckas sparas inte."""
        with self.assertRaises(RuntimeError), self.db.transaction() as tx:
            self.audit.record(tx, "system", "halvfärdig")
            raise RuntimeError("avbrott")
        self.assertEqual(self.audit.entries(), [])


class TestAppendOnly(AuditTestCase):
    def test_update_is_refused_by_database(self):
        """Verifies SR-09: SQLite vägrar ändra en revisionsrad (append-only)."""
        self.fill(1)
        with (
            self.assertRaises(sqlite3.DatabaseError) as ctx,
            self.db.transaction() as tx,
        ):
            tx.execute("UPDATE audit_log SET action = 'ändrad' WHERE seq = 1")
        self.assertIn("append-only", str(ctx.exception))
        self.assertEqual(self.audit.entries()[0].action, "händelse-1")

    def test_delete_is_refused_by_database(self):
        """Verifies SR-09: SQLite vägrar radera en revisionsrad (append-only)."""
        self.fill(1)
        with self.assertRaises(sqlite3.DatabaseError), self.db.transaction() as tx:
            tx.execute("DELETE FROM audit_log")
        self.assertEqual(len(self.audit.entries()), 1)


class TestTamperDetected(AuditTestCase):
    def test_changed_content_is_detected(self):
        """Verifies SR-09: en rad vars innehåll ändrats i efterhand upptäcks."""
        self.fill(4)
        self.tamper("UPDATE audit_log SET details = '{\"nummer\":99}' WHERE seq = 2")
        problems = self.audit.verify()
        self.assertEqual(
            problems, ["rad 2: innehållet har ändrats (hash stämmer inte)"]
        )

    def test_changed_content_with_recomputed_hash_is_detected_by_next_row(self):
        """Verifies SR-09: även om hashen räknas om bryts kedjan vid nästa rad."""
        from aie.audit import entry_hash

        self.fill(4)
        seq, ts, actor, _, details, prev = self.db.connection.execute(
            "SELECT seq, ts, actor, action, details, prev_hash FROM audit_log WHERE seq = 2"
        ).fetchone()
        forged = entry_hash(seq, ts, actor, "förfalskad", details, prev)
        self.tamper(
            "UPDATE audit_log SET action = 'förfalskad', hash = ? WHERE seq = 2",
            (forged,),
        )
        self.assertEqual(
            self.audit.verify(), ["rad 3: prev_hash stämmer inte med föregående rad"]
        )

    def test_deleted_row_is_detected(self):
        """Verifies SR-09: en raderad rad upptäcks."""
        self.fill(4)
        self.tamper("DELETE FROM audit_log WHERE seq = 2")
        problems = self.audit.verify()
        self.assertIn(
            "rad 3: förväntade rad 2 (rad saknas eller har lagts till)", problems
        )
        self.assertIn("rad 3: prev_hash stämmer inte med föregående rad", problems)

    def test_inserted_row_is_detected(self):
        """Verifies SR-09: en rad som skjutits in utanför programmet upptäcks."""
        self.fill(2)
        self.tamper(
            "INSERT INTO audit_log (seq, ts, actor, action, details, prev_hash, hash) "
            "VALUES (3, '2026-01-01T00:00:00+00:00', 'angripare', 'falsk', '{}', 'x', 'y')"
        )
        problems = self.audit.verify()
        self.assertIn("rad 3: prev_hash stämmer inte med föregående rad", problems)
        self.assertIn("rad 3: innehållet har ändrats (hash stämmer inte)", problems)


if __name__ == "__main__":
    unittest.main()
