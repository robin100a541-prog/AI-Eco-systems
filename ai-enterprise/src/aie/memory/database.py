"""SQLite-lagret (Fas 1.4): en databasfil per miljö, migrationer och metadatatabell.

`Database.open(data_dir, environment)`:
1. Skapar `data_dir` om den saknas och öppnar `<data_dir>/<environment>.db`.
2. Slår på främmande nycklar, WAL och `synchronous=FULL` (inget tappas vid strömavbrott).
3. Kontrollerar redan körda migrationer mot koden. En ändrad migration, eller en databas
   från en nyare version av koden, stoppar uppstart.
4. Kör nya migrationer, var och en i en egen transaktion.
5. Kontrollerar att databasen tillhör rätt miljö. En `prod`-databas kan aldrig öppnas
   som `sim` och tvärtom, även om filen bytt namn (SR-11).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from .migrations import MIGRATIONS, Migration, validate_migrations

ENVIRONMENTS = ("sim", "prod")
BUSY_TIMEOUT_MS = 5_000
MIN_SQLITE = (3, 37, 0)  # STRICT-tabeller: SQLite själv kontrollerar kolumntyperna


class StorageError(Exception):
    """Databasen kan inte användas säkert. Systemet ska då inte starta."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """En öppen databas. Använd som `with Database.open(...) as db:` så att den alltid stängs."""

    def __init__(self, connection: sqlite3.Connection, path: Path, environment: str) -> None:
        self.connection = connection
        self.path = path
        self.environment = environment

    @classmethod
    def open(
        cls,
        data_dir: Path | str,
        environment: str,
        migrations: tuple[Migration, ...] = MIGRATIONS,
    ) -> Database:
        if environment not in ENVIRONMENTS:
            raise StorageError(f"okänd miljö {environment!r} (måste vara 'sim' eller 'prod')")
        if sqlite3.sqlite_version_info < MIN_SQLITE:
            raise StorageError(
                f"SQLite {sqlite3.sqlite_version} är för gammal; minst "
                f"{'.'.join(map(str, MIN_SQLITE))} krävs. Uppdatera Python."
            )
        validate_migrations(migrations)

        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / f"{environment}.db"

        # isolation_level=None: inga dolda transaktioner, vi styr BEGIN/COMMIT själva.
        connection = sqlite3.connect(path, isolation_level=None)
        db = cls(connection, path, environment)
        try:
            db._configure()
            db._migrate(migrations)
            db._check_environment()
        except BaseException:
            connection.close()
            raise
        return db

    # --- Publikt API -------------------------------------------------------------------

    @property
    def schema_version(self) -> int:
        row = self.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return row[0] or 0

    def metadata(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT key, value FROM metadata"))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Allt i blocket sparas tillsammans eller inte alls."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- Uppstart ------------------------------------------------------------------------

    def _configure(self) -> None:
        execute = self.connection.execute
        execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        execute("PRAGMA foreign_keys = ON")
        execute("PRAGMA journal_mode = WAL")
        execute("PRAGMA synchronous = FULL")

    def _applied(self) -> dict[int, str]:
        """Version → kontrollsumma för körda migrationer. Tom för en ny databas."""
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if not exists:
            return {}
        return dict(self.connection.execute("SELECT version, checksum FROM schema_migrations"))

    def _migrate(self, migrations: tuple[Migration, ...]) -> None:
        applied = self._applied()
        known = {m.version: m for m in migrations}

        newer = sorted(v for v in applied if v not in known)
        if newer:
            raise StorageError(
                f"{self.path.name} har schemaversion {max(newer)}, men koden känner bara till "
                f"version {len(migrations)}. Uppdatera koden; databasen nedgraderas aldrig."
            )
        changed = [v for v, checksum in applied.items() if known[v].checksum != checksum]
        if changed:
            raise StorageError(
                f"migration {', '.join(map(str, sorted(changed)))} har ändrats efter att den körts "
                f"mot {self.path.name}. Ändra aldrig en körd migration; lägg till en ny."
            )

        for migration in migrations:
            if migration.version not in applied:
                self._apply(migration, first=not applied and migration.version == 1)

    def _apply(self, migration: Migration, first: bool) -> None:
        try:
            with self.transaction() as tx:
                for statement in migration.statements:
                    tx.execute(statement)
                if first:
                    tx.executemany(
                        "INSERT INTO metadata (key, value) VALUES (?, ?)",
                        [
                            ("environment", self.environment),
                            ("created_at", _now()),
                            ("created_by_version", __version__),
                        ],
                    )
                tx.execute(
                    "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, _now()),
                )
        except sqlite3.Error as exc:
            raise StorageError(
                f"migration {migration.version} ({migration.name}) misslyckades och rullades "
                f"tillbaka: {exc}"
            ) from exc

    def _check_environment(self) -> None:
        stored = self.metadata().get("environment")
        if stored != self.environment:
            raise StorageError(
                f"{self.path.name} tillhör miljön {stored!r}, men konfigurationen säger "
                f"{self.environment!r}. Simulerade och verkliga data får aldrig blandas (SR-11)."
            )
