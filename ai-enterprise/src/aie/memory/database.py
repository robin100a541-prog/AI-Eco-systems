"""SQLite-lagret (Fas 1.4): en databasfil per miljö, migrationer och metadatatabell.

`Database.open(data_dir, environment)`:
1. Skapar `data_dir` om den saknas och öppnar `<data_dir>/<environment>.db`.
2. Slår på främmande nycklar, WAL och `synchronous=FULL` (inget tappas vid strömavbrott).
3. Kontrollerar redan körda migrationer mot koden. En ändrad migration, eller en databas
   från en nyare version av koden, stoppar uppstart.
4. Kör nya migrationer, var och en i en egen transaktion.
5. Kontrollerar att databasen tillhör rätt miljö. En `prod`-databas kan aldrig öppnas
   som `sim` och tvärtom, även om filen bytt namn (SR-11).

`open_database(config.system)` gör samma sak med `data_dir` och miljön från konfigurationen.
Fel loggas med Fas 1.3-loggningen (loggern `aie.memory`) innan de kastas vidare, och en
transaktion som rullas tillbaka loggas som en varning (FR-04).
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..config import SystemConfig
from ..monitoring import get_logger
from .migrations import MIGRATIONS, Migration, validate_migrations

log = get_logger("memory")

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
        try:
            db = cls._open(Path(data_dir), environment, migrations)
        except StorageError as exc:
            log.error("databasen kunde inte öppnas: %s", exc)
            raise
        log.info(
            "databasen öppnad",
            extra={"fields": {"path": str(db.path), "environment": environment, "schema_version": db.schema_version}},
        )
        return db

    @classmethod
    def _open(cls, data_dir: Path, environment: str, migrations: tuple[Migration, ...]) -> Database:
        if environment not in ENVIRONMENTS:
            raise StorageError(f"okänd miljö {environment!r} (måste vara 'sim' eller 'prod')")
        if sqlite3.sqlite_version_info < MIN_SQLITE:
            raise StorageError(
                f"SQLite {sqlite3.sqlite_version} är för gammal; minst "
                f"{'.'.join(map(str, MIN_SQLITE))} krävs. Uppdatera Python."
            )
        validate_migrations(migrations)

        path = data_dir / f"{environment}.db"
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            # isolation_level=None: inga dolda transaktioner, vi styr BEGIN/COMMIT själva.
            connection = sqlite3.connect(path, isolation_level=None)
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(f"data_dir '{data_dir}' eller {path.name} kan inte öppnas: {exc}") from exc
        db = cls(connection, path, environment)
        try:
            db._configure()
            db._migrate(migrations)
            db._check_environment()
        except sqlite3.Error as exc:
            connection.close()
            raise StorageError(f"{path.name} kan inte användas: {exc}") from exc
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
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            log.warning("transaktionen rullades tillbaka: %s: %s", type(exc).__name__, exc)
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
        self._enable_wal()
        execute("PRAGMA synchronous = FULL")

    def _enable_wal(self) -> None:
        """Slår på WAL. Försöker igen i upp till BUSY_TIMEOUT_MS om filen är låst.

        `PRAGMA journal_mode = WAL` väntar inte på busy_timeout: öppnar två processer en ny
        databas samtidigt svarar SQLite direkt "database is locked". Det är tillfälligt, så
        vi försöker igen en kort stund i stället för att vägra starta.
        """
        deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
        while True:
            try:
                mode = self.connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or time.monotonic() >= deadline:
                    raise
            else:
                if mode == "wal":
                    return
                if time.monotonic() >= deadline:
                    raise sqlite3.OperationalError(f"kunde inte slå på WAL (läge: {mode})")
            time.sleep(0.01)

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
                # BEGIN IMMEDIATE ger skrivlåset först här. En annan process (till exempel
                # `aie status` samtidigt som `aie start` på en ny databas) kan ha kört samma
                # migration medan vi väntade, så kontrollera igen under låset.
                if migration.version in self._applied():
                    return
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


def open_database(system: SystemConfig, migrations: tuple[Migration, ...] = MIGRATIONS) -> Database:
    """Öppnar databasen i `data_dir` för miljön i konfigurationen (FR-03, SR-11)."""
    return Database.open(system.data_dir, system.environment, migrations)
