"""Databasschemats migrationer (Fas 1.4, FR-03).

Regler:
- Versionerna är 1, 2, 3 … utan luckor. En ny migration läggs alltid sist.
- En migration som redan körts ändras **aldrig**. Kontrollsumman sparas i databasen,
  och `Database.open` vägrar starta om koden och databasen inte stämmer överens.
- Varje migration är en lista med enskilda SQL-satser. `executescript` används inte,
  eftersom den gör en egen COMMIT och då kan en halvfärdig migration bli kvar.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        """SHA-256 över satserna. Avslöjar en migration som ändrats i efterhand."""
        return hashlib.sha256("\n;\n".join(self.statements).encode("utf-8")).hexdigest()


def validate_migrations(migrations: tuple[Migration, ...]) -> None:
    """Kastar `ValueError` om versionerna inte är 1..N i ordning."""
    versions = [m.version for m in migrations]
    expected = list(range(1, len(migrations) + 1))
    if versions != expected:
        raise ValueError(f"migrationernas versioner måste vara {expected}, fick {versions}")


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="metadata",
        statements=(
            # Nyckel/värde om själva databasen: miljö, när den skapades, med vilken version.
            """
            CREATE TABLE metadata (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) STRICT
            """,
            # En rad per körd migration. Raderna ändras aldrig efteråt.
            """
            CREATE TABLE schema_migrations (
                version    INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                checksum   TEXT NOT NULL,
                applied_at TEXT NOT NULL
            ) STRICT
            """,
        ),
    ),
    Migration(
        version=2,
        name="audit_log",
        statements=(
            # Fas 1.5 (SR-09): append-only och hashkedjad. Se src/aie/audit/log.py.
            """
            CREATE TABLE audit_log (
                seq       INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                actor     TEXT NOT NULL,
                action    TEXT NOT NULL,
                details   TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash      TEXT NOT NULL UNIQUE
            ) STRICT
            """,
            # Databasen själv vägrar ändra eller radera rader, oavsett vilken kod som försöker.
            """
            CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
            BEGIN
                SELECT RAISE(ABORT, 'audit_log är append-only: rader får inte ändras');
            END
            """,
            """
            CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
            BEGIN
                SELECT RAISE(ABORT, 'audit_log är append-only: rader får inte raderas');
            END
            """,
        ),
    ),
    Migration(
        version=3,
        name="runtime_state",
        statements=(
            # Fas 1.6 (FR-01): systemets driftläge. Exakt en rad (id = 1).
            # stop_requested sätts av `aie stop` och läses av den process som kör `aie start`,
            # så stopp fungerar likadant på Windows, macOS och Linux utan signaler.
            """
            CREATE TABLE runtime_state (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                state          TEXT NOT NULL CHECK (state IN ('stopped', 'running')),
                pid            INTEGER,
                started_at     TEXT,
                stopped_at     TEXT,
                stop_requested INTEGER NOT NULL DEFAULT 0 CHECK (stop_requested IN (0, 1)),
                last_exit      TEXT CHECK (last_exit IN ('clean', 'error', 'unclean'))
            ) STRICT
            """,
            "INSERT INTO runtime_state (id, state) VALUES (1, 'stopped')",
        ),
    ),
)

validate_migrations(MIGRATIONS)
