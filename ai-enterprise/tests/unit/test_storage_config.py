"""Tester för Fas 1.4b: databasen öppnas från konfigurationen och fel loggas.

Verifierar FR-03 och FR-04. Kompletterar test_storage.py (Fas 1.4).
"""

import io
import json
import tempfile
import unittest
from pathlib import Path

from aie.config import SystemConfig
from aie.memory import MIGRATIONS, Database, Migration, StorageError, open_database
from aie.monitoring import LOG_FILE_NAME, setup_logging, shutdown_logging

NOTES = Migration(
    len(MIGRATIONS) + 1,  # alltid efter de riktiga migrationerna
    "notes",
    ("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL) STRICT",),
)


class StorageConfigTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.log_dir = self.dir / "logs"
        setup_logging(self.log_dir, "INFO", stream=io.StringIO())
        self.addCleanup(shutdown_logging)  # körs före cleanup av mappen (LIFO)

    def system(self, **changes):
        values = {
            "environment": "sim",
            "data_dir": self.dir / "data",
            "log_dir": self.log_dir,
            "base_currency": "SIM",
            "config_version": 1,
        }
        return SystemConfig(**{**values, **changes})

    def log_entries(self):
        shutdown_logging()  # stänger filen så att allt är skrivet
        path = self.log_dir / LOG_FILE_NAME
        return [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]


class TestOpenFromConfig(StorageConfigTestCase):
    def test_database_lives_in_data_dir_from_config(self):
        """Verifies FR-03: databasen skapas som <data_dir>/<miljö>.db enligt konfigurationen."""
        with open_database(self.system()) as db:
            self.assertEqual(db.path, self.dir / "data" / "sim.db")
            self.assertEqual(db.metadata()["environment"], "sim")
        self.assertTrue((self.dir / "data" / "sim.db").is_file())

    def test_data_survives_close_and_reopen_via_config(self):
        """Verifies FR-03: data som sparats via konfigurationen finns kvar efter stängning och ny öppning."""
        migrations = (*MIGRATIONS, NOTES)
        with open_database(self.system(), migrations) as db, db.transaction() as tx:
            tx.execute("INSERT INTO notes (text) VALUES ('kvar efter omstart')")
        with open_database(self.system(), migrations) as db:
            rows = db.connection.execute("SELECT text FROM notes").fetchall()
        self.assertEqual(rows, [("kvar efter omstart",)])

    def test_open_is_logged(self):
        """Verifies FR-04: att databasen öppnas loggas med sökväg, miljö och schemaversion."""
        open_database(self.system()).close()
        [entry] = [e for e in self.log_entries() if e["source"] == "aie.memory"]
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["fields"]["environment"], "sim")
        self.assertEqual(entry["fields"]["schema_version"], len(MIGRATIONS))


class TestErrorsLogged(StorageConfigTestCase):
    def test_data_dir_that_cannot_be_created_is_storage_error_and_logged(self):
        """Verifies FR-03, FR-04: en data_dir som inte kan skapas ger StorageError, och felet loggas."""
        blocker = self.dir / "fil"
        blocker.write_text("x", encoding="utf-8")
        with self.assertRaises(StorageError) as ctx:
            open_database(self.system(data_dir=blocker / "data"))
        self.assertIn("kan inte öppnas", str(ctx.exception))
        errors = [e for e in self.log_entries() if e["level"] == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("databasen kunde inte öppnas", errors[0]["message"])

    def test_wrong_environment_is_logged(self):
        """Verifies FR-04: att en prod-databas vägras som sim loggas som fel."""
        Database.open(self.dir / "data", "prod").close()
        (self.dir / "data" / "prod.db").rename(self.dir / "data" / "sim.db")
        with self.assertRaises(StorageError):
            open_database(self.system())
        errors = [e["message"] for e in self.log_entries() if e["level"] == "ERROR"]
        self.assertTrue(any("tillhör miljön 'prod'" in m for m in errors), errors)

    def test_failed_write_rolls_back_and_is_logged(self):
        """Verifies FR-03, FR-04: ett fel mitt i en skrivning rullar tillbaka allt och loggas som varning."""
        with open_database(self.system(), (*MIGRATIONS, NOTES)) as db:
            with self.assertRaises(RuntimeError), db.transaction() as tx:
                tx.execute("INSERT INTO notes (text) VALUES ('första')")
                tx.execute("INSERT INTO notes (text) VALUES ('andra')")
                raise RuntimeError("avbrott mitt i skrivningen")
            count = db.connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        self.assertEqual(count, 0)
        warnings = [e["message"] for e in self.log_entries() if e["level"] == "WARNING"]
        self.assertIn(
            "transaktionen rullades tillbaka: RuntimeError: avbrott mitt i skrivningen",
            warnings,
        )

    def test_sql_error_inside_transaction_rolls_back(self):
        """Verifies FR-03: ett SQL-fel (NOT NULL) i en transaktion rullar tillbaka även tidigare rader."""
        import sqlite3

        with open_database(self.system(), (*MIGRATIONS, NOTES)) as db:
            with self.assertRaises(sqlite3.IntegrityError), db.transaction() as tx:
                tx.execute("INSERT INTO notes (text) VALUES ('ok')")
                tx.execute("INSERT INTO notes (text) VALUES (NULL)")
            self.assertEqual(
                db.connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0
            )


if __name__ == "__main__":
    unittest.main()
