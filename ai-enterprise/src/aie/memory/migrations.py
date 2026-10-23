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
    Migration(
        version=4,
        name="agent_registry",
        statements=(
            # Fas 2 (FR-05, FR-06, SR-14). Se src/aie/agents/registry.py.
            """
            CREATE TABLE agents (
                agent_id   TEXT PRIMARY KEY,
                role       TEXT NOT NULL,
                department TEXT NOT NULL,
                manager_id TEXT REFERENCES agents (agent_id),
                state      TEXT NOT NULL CHECK (state IN (
                    'PROPOSED', 'CREATED', 'TESTING', 'ACTIVE', 'PROBATION', 'SUSPENDED', 'RETIRED')),
                created_at TEXT NOT NULL
            ) STRICT
            """,
            # En agent raderas aldrig (SR-14). Bara status får ändras; roll och chef är fasta.
            """
            CREATE TRIGGER agents_no_delete BEFORE DELETE ON agents
            BEGIN
                SELECT RAISE(ABORT, 'agenter raderas aldrig; avveckla med status RETIRED');
            END
            """,
            """
            CREATE TRIGGER agents_fixed_identity
            BEFORE UPDATE OF agent_id, role, department, manager_id, created_at ON agents
            BEGIN
                SELECT RAISE(ABORT, 'bara status får ändras på en agent');
            END
            """,
            # Historiken över statusändringar. Append-only, som audit_log.
            """
            CREATE TABLE agent_state_changes (
                id         INTEGER PRIMARY KEY,
                agent_id   TEXT NOT NULL REFERENCES agents (agent_id),
                old_state  TEXT,
                new_state  TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                reason     TEXT NOT NULL,
                at         TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER agent_state_changes_no_update BEFORE UPDATE ON agent_state_changes
            BEGIN
                SELECT RAISE(ABORT, 'agent_state_changes är append-only');
            END
            """,
            """
            CREATE TRIGGER agent_state_changes_no_delete BEFORE DELETE ON agent_state_changes
            BEGIN
                SELECT RAISE(ABORT, 'agent_state_changes är append-only');
            END
            """,
        ),
    ),
    Migration(
        version=5,
        name="tasks",
        statements=(
            # Fas 2 (FR-07). Se src/aie/orchestration/tasks.py.
            """
            CREATE TABLE tasks (
                task_id     INTEGER PRIMARY KEY,
                title       TEXT NOT NULL CHECK (length(trim(title)) > 0),
                description TEXT NOT NULL,
                created_by  TEXT NOT NULL,
                owner_id    TEXT REFERENCES agents (agent_id),
                status      TEXT NOT NULL CHECK (status IN (
                    'open', 'assigned', 'in_progress', 'blocked', 'done', 'cancelled')),
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                CHECK (status = 'open' OR status = 'cancelled' OR owner_id IS NOT NULL)
            ) STRICT
            """,
            """
            CREATE TRIGGER tasks_no_delete BEFORE DELETE ON tasks
            BEGIN
                SELECT RAISE(ABORT, 'uppgifter raderas aldrig; avbryt med status cancelled');
            END
            """,
            """
            CREATE TRIGGER tasks_final_status BEFORE UPDATE ON tasks
            WHEN OLD.status IN ('done', 'cancelled')
            BEGIN
                SELECT RAISE(ABORT, 'en avslutad uppgift kan inte ändras');
            END
            """,
            # Varje händelse för en uppgift. Append-only.
            """
            CREATE TABLE task_events (
                id         INTEGER PRIMARY KEY,
                task_id    INTEGER NOT NULL REFERENCES tasks (task_id),
                event      TEXT NOT NULL,
                actor      TEXT NOT NULL,
                owner_id   TEXT,
                old_status TEXT,
                new_status TEXT NOT NULL,
                note       TEXT NOT NULL,
                at         TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER task_events_no_update BEFORE UPDATE ON task_events
            BEGIN
                SELECT RAISE(ABORT, 'task_events är append-only');
            END
            """,
            """
            CREATE TRIGGER task_events_no_delete BEFORE DELETE ON task_events
            BEGIN
                SELECT RAISE(ABORT, 'task_events är append-only');
            END
            """,
        ),
    ),
    Migration(
        version=6,
        name="provider_usage",
        statements=(
            # Fas 2 (DR-12): förbrukning per leverantör och UTC-dygn. Räknas *innan* anropet
            # skickas, så att gränsen aldrig kan överskridas, inte ens av samtidiga anrop.
            """
            CREATE TABLE provider_usage (
                day      TEXT NOT NULL,
                provider TEXT NOT NULL,
                calls    INTEGER NOT NULL DEFAULT 0 CHECK (calls >= 0),
                tokens   INTEGER NOT NULL DEFAULT 0 CHECK (tokens >= 0),
                PRIMARY KEY (day, provider)
            ) STRICT
            """,
        ),
    ),
    Migration(
        version=7,
        name="decisions",
        statements=(
            # Fas 3 (FR-10, §20 steg 7): beslutsloggen. Varje beslut hör till en uppgift och
            # innehåller de åtta fälten i §20 steg 7. Append-only: ett beslut ändras aldrig,
            # ett nytt beslut kan ersätta ett gammalt (supersedes).
            """
            CREATE TABLE decisions (
                decision_id     INTEGER PRIMARY KEY,
                task_id         INTEGER NOT NULL REFERENCES tasks (task_id),
                decided_by      TEXT NOT NULL,
                chosen_action   TEXT NOT NULL CHECK (length(trim(chosen_action)) > 0),
                reasoning       TEXT NOT NULL CHECK (length(trim(reasoning)) > 0),
                evidence        TEXT NOT NULL CHECK (json_valid(evidence) AND json_array_length(evidence) > 0),
                budget_minor    INTEGER NOT NULL CHECK (budget_minor >= 0),
                currency        TEXT NOT NULL,
                risk_class      TEXT NOT NULL CHECK (risk_class IN ('low', 'medium', 'high', 'critical')),
                expected_result TEXT NOT NULL CHECK (length(trim(expected_result)) > 0),
                stop_conditions TEXT NOT NULL CHECK (length(trim(stop_conditions)) > 0),
                follow_up       TEXT NOT NULL CHECK (length(trim(follow_up)) > 0),
                supersedes      INTEGER REFERENCES decisions (decision_id),
                decided_at      TEXT NOT NULL
            ) STRICT
            """,
            "CREATE INDEX decisions_by_task ON decisions (task_id)",
            """
            CREATE TRIGGER decisions_no_update BEFORE UPDATE ON decisions
            BEGIN
                SELECT RAISE(ABORT, 'decisions är append-only: ett beslut ändras aldrig');
            END
            """,
            """
            CREATE TRIGGER decisions_no_delete BEFORE DELETE ON decisions
            BEGIN
                SELECT RAISE(ABORT, 'decisions är append-only: ett beslut raderas aldrig');
            END
            """,
        ),
    ),
)

validate_migrations(MIGRATIONS)
