"""Tester för src/aie/memory (Fas 1.4). Verifierar FR-03 och SR-11."""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie import __version__
from aie.memory import MIGRATIONS, Database, Migration, StorageError

NOTES = Migration(
    version=2,
    name="notes",
    statements=("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL) STRICT",),
)


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"

    def open(self, environment="sim", migrations=MIGRATIONS):
        db = Database.open(self.data_dir, environment, migrations)
        self.addCleanup(db.close)  # stänger även om testet misslyckas (Windows låser filen)
        return db


class TestCreate(StorageTestCase):
    def test_creates_one_file_per_environment(self):
        """Verifies FR-03: data_dir skapas och databasen heter <miljö>.db."""
        self.open("sim").close()
        self.open("prod").close()
        self.assertTrue((self.data_dir / "sim.db").is_file())
        self.assertTrue((self.data_dir / "prod.db").is_file())

    def test_metadata_records_environment_and_version(self):
        """Verifies FR-03: metadatatabellen har miljö, skapandetid och programversion."""
        with self.open() as db:
            meta = db.metadata()
            self.assertEqual(meta["environment"], "sim")
            self.assertEqual(meta["created_by_version"], __version__)
            self.assertIn("created_at", meta)
            self.assertEqual(db.schema_version, len(MIGRATIONS))

    def test_safety_pragmas_are_on(self):
        """Verifies FR-03: främmande nycklar, WAL och synchronous=FULL är påslagna."""
        with self.open() as db:
            execute = db.connection.execute
            self.assertEqual(execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(execute("PRAGMA synchronous").fetchone()[0], 2)  # 2 = FULL

    def test_unknown_environment_refused(self):
        """Verifies SR-11: bara sim och prod finns."""
        with self.assertRaises(StorageError):
            Database.open(self.data_dir, "test")
        self.assertFalse(self.data_dir.exists())


class TestRestart(StorageTestCase):
    def test_data_survives_restart(self):
        """Verifies FR-03: data som sparats finns kvar efter att databasen stängts och öppnats igen."""
        migrations = (*MIGRATIONS, NOTES)
        with self.open(migrations=migrations) as db, db.transaction() as tx:
            tx.execute("INSERT INTO notes (text) VALUES ('överlever omstart')")
        with self.open(migrations=migrations) as db:
            rows = db.connection.execute("SELECT text FROM notes").fetchall()
        self.assertEqual(rows, [("överlever omstart",)])

    def test_reopen_does_not_rerun_migrations(self):
        """Verifies FR-03: körda migrationer körs inte igen och metadata skrivs inte om."""
        with self.open() as db:
            first = (db.metadata(), db.connection.execute("SELECT * FROM schema_migrations").fetchall())
        with self.open() as db:
            second = (db.metadata(), db.connection.execute("SELECT * FROM schema_migrations").fetchall())
        self.assertEqual(first, second)

    def test_new_migration_upgrades_existing_database(self):
        """Verifies FR-03: en ny migration körs på en befintlig databas utan att data försvinner."""
        with self.open() as db:
            created_at = db.metadata()["created_at"]
        with self.open(migrations=(*MIGRATIONS, NOTES)) as db:
            self.assertEqual(db.schema_version, 2)
            self.assertEqual(db.metadata()["created_at"], created_at)

    def test_rolled_back_transaction_saves_nothing(self):
        """Verifies FR-03: ett fel mitt i en transaktion sparar ingenting."""
        with self.open(migrations=(*MIGRATIONS, NOTES)) as db:
            with self.assertRaises(RuntimeError), db.transaction() as tx:
                tx.execute("INSERT INTO notes (text) VALUES ('halvfärdig')")
                raise RuntimeError("avbrott")
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)


class TestRefuseUnsafe(StorageTestCase):
    def test_prod_database_cannot_be_opened_as_sim(self):
        """Verifies SR-11: en prod-databas som döpts om till sim.db vägrar öppnas."""
        self.open("prod").close()
        self.data_dir.joinpath("sim.db").unlink(missing_ok=True)
        shutil.copy(self.data_dir / "prod.db", self.data_dir / "sim.db")
        with self.assertRaises(StorageError) as ctx:
            Database.open(self.data_dir, "sim")
        self.assertIn("tillhör miljön 'prod'", str(ctx.exception))

    def test_database_from_newer_code_refused(self):
        """Verifies FR-03: en databas med högre schemaversion än koden öppnas aldrig (ingen nedgradering)."""
        self.open(migrations=(*MIGRATIONS, NOTES)).close()
        with self.assertRaises(StorageError) as ctx:
            Database.open(self.data_dir, "sim", MIGRATIONS)
        self.assertIn("har schemaversion 2", str(ctx.exception))

    def test_changed_migration_detected(self):
        """Verifies FR-03: en migration som ändrats efter att den körts stoppar uppstart."""
        self.open(migrations=(*MIGRATIONS, NOTES)).close()
        tampered = Migration(2, "notes", ("CREATE TABLE notes (id INTEGER PRIMARY KEY) STRICT",))
        with self.assertRaises(StorageError) as ctx:
            Database.open(self.data_dir, "sim", (*MIGRATIONS, tampered))
        self.assertIn("migration 2 har ändrats", str(ctx.exception))

    def test_failed_migration_rolls_back_completely(self):
        """Verifies FR-03: en migration som misslyckas halvvägs lämnar inget efter sig."""
        self.open().close()
        broken = Migration(2, "broken", ("CREATE TABLE half (id INTEGER) STRICT", "NOT VALID SQL"))
        with self.assertRaises(StorageError) as ctx:
            Database.open(self.data_dir, "sim", (*MIGRATIONS, broken))
        self.assertIn("rullades tillbaka", str(ctx.exception))
        with self.open() as db:
            self.assertEqual(db.schema_version, 1)
            tables = {r[0] for r in db.connection.execute("SELECT name FROM sqlite_master")}
            self.assertNotIn("half", tables)

    def test_migration_versions_must_be_contiguous(self):
        """Verifies FR-03: migrationer med luckor i versionerna avvisas."""
        gap = Migration(3, "gap", ("SELECT 1",))
        with self.assertRaises(ValueError):
            Database.open(self.data_dir, "sim", (*MIGRATIONS, gap))

    def test_strict_tables_reject_wrong_types(self):
        """Verifies FR-03: SQLite själv avvisar fel kolumntyp (STRICT)."""
        with self.open(migrations=(*MIGRATIONS, NOTES)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.connection.execute("INSERT INTO notes (id, text) VALUES ('inte ett tal', 'x')")


if __name__ == "__main__":
    unittest.main()
