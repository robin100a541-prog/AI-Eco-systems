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
        name="control_stops",
        statements=(
            # Fas 3b (SR-05): stopp från kontrollfunktionerna. Se src/aie/authorization/stops.py.
            # Ett stopp raderas aldrig. Det hävs genom att lifted_* fylls i, och det kan bara göras en gång.
            """
            CREATE TABLE control_stops (
                stop_id     INTEGER PRIMARY KEY,
                scope_kind  TEXT NOT NULL CHECK (scope_kind IN ('agent', 'department', 'tool')),
                scope_value TEXT NOT NULL,
                reason      TEXT NOT NULL CHECK (length(trim(reason)) > 0),
                placed_by   TEXT NOT NULL,
                placed_at   TEXT NOT NULL,
                lifted_by   TEXT,
                lifted_at   TEXT,
                lift_reason TEXT,
                CHECK ((lifted_by IS NULL) = (lifted_at IS NULL) AND (lifted_at IS NULL) = (lift_reason IS NULL))
            ) STRICT
            """,
            """
            CREATE TRIGGER control_stops_no_delete BEFORE DELETE ON control_stops
            BEGIN
                SELECT RAISE(ABORT, 'stopp raderas aldrig; de hävs');
            END
            """,
            """
            CREATE TRIGGER control_stops_fixed BEFORE UPDATE OF
                stop_id, scope_kind, scope_value, reason, placed_by, placed_at ON control_stops
            BEGIN
                SELECT RAISE(ABORT, 'ett stopp kan inte ändras, bara hävas');
            END
            """,
            """
            CREATE TRIGGER control_stops_lift_once BEFORE UPDATE ON control_stops
            WHEN OLD.lifted_at IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'stoppet är redan hävt');
            END
            """,
        ),
    ),
    Migration(
        version=8,
        name="consultations",
        statements=(
            # Fas 3c (FR-11, §20 steg 5). Se src/aie/collaboration/consultation.py.
            # required_roles och requires_founders räknas fram när samrådet öppnas och ändras aldrig.
            """
            CREATE TABLE consultations (
                consultation_id   INTEGER PRIMARY KEY,
                subject           TEXT NOT NULL CHECK (length(trim(subject)) > 0),
                question          TEXT NOT NULL CHECK (length(trim(question)) > 0),
                opened_by         TEXT NOT NULL,
                amount_minor      INTEGER CHECK (amount_minor IS NULL OR amount_minor >= 0),
                currency          TEXT,
                risk_class        TEXT NOT NULL CHECK (risk_class IN ('low', 'medium', 'high', 'critical')),
                legal             INTEGER NOT NULL CHECK (legal IN (0, 1)),
                required_roles    TEXT NOT NULL,
                requires_founders INTEGER NOT NULL CHECK (requires_founders IN (0, 1)),
                opened_at         TEXT NOT NULL,
                CHECK ((amount_minor IS NULL) = (currency IS NULL))
            ) STRICT
            """,
            """
            CREATE TRIGGER consultations_immutable BEFORE UPDATE ON consultations
            BEGIN
                SELECT RAISE(ABORT, 'ett samråd ändras aldrig; yttranden läggs till');
            END
            """,
            """
            CREATE TRIGGER consultations_no_delete BEFORE DELETE ON consultations
            BEGIN
                SELECT RAISE(ABORT, 'samråd raderas aldrig');
            END
            """,
            # Ett yttrande per roll och samråd. Append-only.
            """
            CREATE TABLE consultation_opinions (
                id              INTEGER PRIMARY KEY,
                consultation_id INTEGER NOT NULL REFERENCES consultations (consultation_id),
                role            TEXT NOT NULL,
                agent_id        TEXT NOT NULL REFERENCES agents (agent_id),
                position        TEXT NOT NULL CHECK (position IN ('support', 'object', 'abstain')),
                reasoning       TEXT NOT NULL CHECK (length(trim(reasoning)) > 0),
                evidence        TEXT NOT NULL,
                at              TEXT NOT NULL,
                UNIQUE (consultation_id, role)
            ) STRICT
            """,
            """
            CREATE TRIGGER consultation_opinions_no_update BEFORE UPDATE ON consultation_opinions
            BEGIN
                SELECT RAISE(ABORT, 'ett yttrande ändras aldrig');
            END
            """,
            """
            CREATE TRIGGER consultation_opinions_no_delete BEFORE DELETE ON consultation_opinions
            BEGIN
                SELECT RAISE(ABORT, 'ett yttrande raderas aldrig');
            END
            """,
        ),
    ),
    Migration(
        version=9,
        name="decisions",
        statements=(
            # Fas 3 (FR-10, §20 steg 7): beslutsloggen. (Robin; nummer 9 eftersom 7 och 8 är Yorgos.) Varje beslut hör till en uppgift och
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
    Migration(
        version=10,
        name="disputes",
        statements=(
            # Fas 3 (FR-12, §21): oenighet mellan agenter (Robin). En tvist gäller en uppgift och ett
            # förslag (åtgärd, budget, riskklass). Ståndpunkterna och händelserna är append-only.
            """
            CREATE TABLE disputes (
                dispute_id          INTEGER PRIMARY KEY,
                task_id             INTEGER NOT NULL REFERENCES tasks (task_id),
                conflict_type       TEXT NOT NULL CHECK (conflict_type IN ('goal', 'data', 'risk', 'method')),
                proposal            TEXT NOT NULL CHECK (length(trim(proposal)) > 0),
                proposal_budget     INTEGER NOT NULL CHECK (proposal_budget >= 0),
                proposal_risk_class TEXT NOT NULL CHECK (proposal_risk_class IN ('low', 'medium', 'high', 'critical')),
                opened_by           TEXT NOT NULL,
                status              TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'escalated')),
                escalated_to        TEXT CHECK (escalated_to IN ('ceo', 'founders')),
                opened_at           TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER disputes_no_delete BEFORE DELETE ON disputes
            BEGIN
                SELECT RAISE(ABORT, 'tvister raderas aldrig');
            END
            """,
            """
            CREATE TRIGGER disputes_final_status BEFORE UPDATE ON disputes
            WHEN OLD.status = 'resolved'
                OR (OLD.status = 'escalated' AND NOT (
                    NEW.status = 'resolved'
                    OR (NEW.status = 'escalated' AND OLD.escalated_to = 'ceo' AND NEW.escalated_to = 'founders')))
            BEGIN
                SELECT RAISE(ABORT, 'en avgjord tvist kan inte ändras');
            END
            """,
            """
            CREATE TABLE dispute_positions (
                position_id INTEGER PRIMARY KEY,
                dispute_id  INTEGER NOT NULL REFERENCES disputes (dispute_id),
                agent_id    TEXT NOT NULL,
                claim       TEXT NOT NULL CHECK (length(trim(claim)) > 0),
                evidence    TEXT NOT NULL CHECK (json_valid(evidence)),
                recorded_at TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE dispute_events (
                id         INTEGER PRIMARY KEY,
                dispute_id INTEGER NOT NULL REFERENCES disputes (dispute_id),
                event      TEXT NOT NULL,
                actor      TEXT NOT NULL,
                note       TEXT NOT NULL,
                at         TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER dispute_positions_no_update BEFORE UPDATE ON dispute_positions
            BEGIN SELECT RAISE(ABORT, 'dispute_positions är append-only'); END
            """,
            """
            CREATE TRIGGER dispute_positions_no_delete BEFORE DELETE ON dispute_positions
            BEGIN SELECT RAISE(ABORT, 'dispute_positions är append-only'); END
            """,
            """
            CREATE TRIGGER dispute_events_no_update BEFORE UPDATE ON dispute_events
            BEGIN SELECT RAISE(ABORT, 'dispute_events är append-only'); END
            """,
            """
            CREATE TRIGGER dispute_events_no_delete BEFORE DELETE ON dispute_events
            BEGIN SELECT RAISE(ABORT, 'dispute_events är append-only'); END
            """,
        ),
    ),
    Migration(
        version=11,
        name="legal_holds",
        statements=(
            # Fas 3h (SR-16, §6): juridisk eller avtalsmässig konflikt (Yorgo). Uppgiften hålls tills
            # Compliance har yttrat sig. En hållning raderas aldrig och släpps bara en gång.
            """
            CREATE TABLE legal_holds (
                hold_id         INTEGER PRIMARY KEY,
                task_id         INTEGER NOT NULL REFERENCES tasks (task_id),
                description     TEXT NOT NULL CHECK (length(trim(description)) > 0),
                evidence        TEXT NOT NULL CHECK (json_valid(evidence) AND json_array_length(evidence) > 0),
                raised_by       TEXT NOT NULL,
                consultation_id INTEGER NOT NULL REFERENCES consultations (consultation_id),
                raised_at       TEXT NOT NULL,
                released_by     TEXT,
                released_at     TEXT,
                outcome         TEXT CHECK (outcome IN ('cleared', 'cancelled')),
                release_reason  TEXT,
                CHECK ((released_at IS NULL) = (outcome IS NULL) AND (outcome IS NULL) = (released_by IS NULL)
                       AND (outcome IS NULL) = (release_reason IS NULL))
            ) STRICT
            """,
            # Högst en aktiv hållning per uppgift.
            "CREATE UNIQUE INDEX legal_holds_one_active ON legal_holds (task_id) WHERE released_at IS NULL",
            """
            CREATE TRIGGER legal_holds_no_delete BEFORE DELETE ON legal_holds
            BEGIN SELECT RAISE(ABORT, 'juridiska hållningar raderas aldrig'); END
            """,
            """
            CREATE TRIGGER legal_holds_fixed BEFORE UPDATE OF
                hold_id, task_id, description, evidence, raised_by, consultation_id, raised_at ON legal_holds
            BEGIN SELECT RAISE(ABORT, 'en hållning kan inte ändras, bara släppas'); END
            """,
            """
            CREATE TRIGGER legal_holds_release_once BEFORE UPDATE ON legal_holds
            WHEN OLD.released_at IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'hållningen är redan släppt'); END
            """,
        ),
    ),
    Migration(
        version=12,
        name="approvals",
        statements=(
            # Fas 3 (FR-13, D-019): grundarnas godkännandekö (Robin). En förfrågan kräver 1 eller 2
            # grundare enligt D-019. Rösterna är append-only; en avgjord förfrågan ändras aldrig.
            """
            CREATE TABLE approval_requests (
                request_id         INTEGER PRIMARY KEY,
                kind               TEXT NOT NULL CHECK (kind IN ('decision', 'dispute', 'governance')),
                task_id            INTEGER NOT NULL REFERENCES tasks (task_id),
                dispute_id         INTEGER REFERENCES disputes (dispute_id),
                requested_by       TEXT NOT NULL,
                reason             TEXT NOT NULL CHECK (length(trim(reason)) > 0),
                amount_minor       INTEGER NOT NULL CHECK (amount_minor >= 0),
                currency           TEXT NOT NULL,
                required_approvals INTEGER NOT NULL CHECK (required_approvals IN (1, 2)),
                payload            TEXT NOT NULL CHECK (json_valid(payload)),
                status             TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
                outcome_decision   INTEGER REFERENCES decisions (decision_id),
                created_at         TEXT NOT NULL,
                decided_at         TEXT,
                CHECK (kind != 'dispute' OR dispute_id IS NOT NULL)
            ) STRICT
            """,
            """
            CREATE TRIGGER approval_requests_no_delete BEFORE DELETE ON approval_requests
            BEGIN SELECT RAISE(ABORT, 'förfrågningar i godkännandekön raderas aldrig'); END
            """,
            """
            CREATE TRIGGER approval_requests_final BEFORE UPDATE ON approval_requests
            WHEN OLD.status != 'pending'
            BEGIN SELECT RAISE(ABORT, 'en avgjord förfrågan kan inte ändras'); END
            """,
            """
            CREATE TABLE approval_votes (
                id         INTEGER PRIMARY KEY,
                request_id INTEGER NOT NULL REFERENCES approval_requests (request_id),
                founder    TEXT NOT NULL,
                verdict    TEXT NOT NULL CHECK (verdict IN ('approve', 'reject')),
                note       TEXT NOT NULL,
                at         TEXT NOT NULL,
                UNIQUE (request_id, founder)
            ) STRICT
            """,
            """
            CREATE TRIGGER approval_votes_no_update BEFORE UPDATE ON approval_votes
            BEGIN SELECT RAISE(ABORT, 'approval_votes är append-only'); END
            """,
            """
            CREATE TRIGGER approval_votes_no_delete BEFORE DELETE ON approval_votes
            BEGIN SELECT RAISE(ABORT, 'approval_votes är append-only'); END
            """,
        ),
    ),
    Migration(
        version=13,
        name="ledger",
        statements=(
            # Fas 4a (§40, ER-06–08, ER-15, SR-12): ledgern (Robin). En post ändras eller raderas aldrig.
            # Fel rättas med en korrigeringspost (`corrects`). Status ändras bara framåt, som händelser.
            """
            CREATE TABLE ledger_entries (
                entry_id        INTEGER PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE CHECK (length(trim(idempotency_key)) > 0),
                recorded_at     TEXT NOT NULL,
                recorded_by     TEXT NOT NULL CHECK (length(trim(recorded_by)) > 0),
                department      TEXT NOT NULL CHECK (length(trim(department)) > 0),
                amount_minor    INTEGER NOT NULL CHECK (amount_minor != 0),
                currency        TEXT NOT NULL CHECK (length(currency) = 3 AND currency = upper(currency)),
                entry_type      TEXT NOT NULL CHECK (entry_type IN
                                ('revenue', 'cost', 'fee', 'refund', 'capital_in', 'capital_out')),
                initiative      TEXT NOT NULL CHECK (length(trim(initiative)) > 0),
                approval_status TEXT NOT NULL CHECK (approval_status IN ('not_required', 'approved', 'unapproved')),
                evidence        TEXT NOT NULL CHECK (json_valid(evidence) AND json_array_length(evidence) > 0),
                external_id     TEXT UNIQUE,
                corrects        INTEGER REFERENCES ledger_entries (entry_id),
                note            TEXT NOT NULL,
                CHECK (amount_minor > 0 OR corrects IS NOT NULL)
            ) STRICT
            """,
            """
            CREATE TRIGGER ledger_entries_no_update BEFORE UPDATE ON ledger_entries
            BEGIN SELECT RAISE(ABORT, 'ledgerposter ändras aldrig; gör en korrigeringspost (ER-08)'); END
            """,
            """
            CREATE TRIGGER ledger_entries_no_delete BEFORE DELETE ON ledger_entries
            BEGIN SELECT RAISE(ABORT, 'ledgerposter raderas aldrig (ER-08)'); END
            """,
            """
            CREATE TABLE ledger_status (
                id       INTEGER PRIMARY KEY,
                entry_id INTEGER NOT NULL REFERENCES ledger_entries (entry_id),
                status   TEXT NOT NULL CHECK (status IN ('pending', 'settled', 'failed', 'cancelled')),
                actor    TEXT NOT NULL,
                note     TEXT NOT NULL,
                at       TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER ledger_status_no_update BEFORE UPDATE ON ledger_status
            BEGIN SELECT RAISE(ABORT, 'ledger_status är append-only'); END
            """,
            """
            CREATE TRIGGER ledger_status_no_delete BEFORE DELETE ON ledger_status
            BEGIN SELECT RAISE(ABORT, 'ledger_status är append-only'); END
            """,
            """
            CREATE TRIGGER ledger_status_forward BEFORE INSERT ON ledger_status
            WHEN EXISTS (SELECT 1 FROM ledger_status WHERE entry_id = NEW.entry_id)
             AND (SELECT status FROM ledger_status WHERE entry_id = NEW.entry_id ORDER BY id DESC LIMIT 1) != 'pending'
            BEGIN SELECT RAISE(ABORT, 'en post med slutlig status kan inte få ny status (§40)'); END
            """,
        ),
    ),
    Migration(
        version=14,
        name="opportunities",
        statements=(
            # Fas 3i (FR-25, D-011, D-025): "Utred möjlighet" (Yorgo). Ett ärende går
            # Research → Compliance → CFO → grundare. Bara stage och status får ändras, och bara framåt.
            """
            CREATE TABLE opportunities (
                opportunity_id INTEGER PRIMARY KEY,
                ref            TEXT,
                kind           TEXT NOT NULL CHECK (kind IN (
                    'channel', 'tool', 'free_api', 'revenue', 'tax', 'terms', 'license', 'market')),
                title          TEXT NOT NULL CHECK (length(trim(title)) > 0),
                question       TEXT NOT NULL CHECK (length(trim(question)) > 0),
                opened_by      TEXT NOT NULL,
                stage          TEXT NOT NULL CHECK (stage IN ('research', 'compliance', 'cfo', 'founders', 'closed')),
                status         TEXT NOT NULL CHECK (status IN (
                    'open', 'unconfirmed_hypothesis', 'verified', 'approved', 'approved_rule', 'rejected')),
                opened_at      TEXT NOT NULL
            ) STRICT
            """,
            "CREATE UNIQUE INDEX opportunities_ref ON opportunities (ref) WHERE ref IS NOT NULL",
            """
            CREATE TRIGGER opportunities_no_delete BEFORE DELETE ON opportunities
            BEGIN SELECT RAISE(ABORT, 'ärenden raderas aldrig'); END
            """,
            """
            CREATE TRIGGER opportunities_fixed BEFORE UPDATE OF
                opportunity_id, ref, kind, title, question, opened_by, opened_at ON opportunities
            BEGIN SELECT RAISE(ABORT, 'bara stage och status får ändras'); END
            """,
            """
            CREATE TRIGGER opportunities_closed BEFORE UPDATE ON opportunities
            WHEN OLD.stage = 'closed'
            BEGIN SELECT RAISE(ABORT, 'ett avslutat ärende ändras aldrig'); END
            """,
            """
            CREATE TABLE opportunity_steps (
                id             INTEGER PRIMARY KEY,
                opportunity_id INTEGER NOT NULL REFERENCES opportunities (opportunity_id),
                stage          TEXT NOT NULL,
                actor          TEXT NOT NULL,
                verdict        TEXT NOT NULL CHECK (verdict IN (
                    'findings', 'ok', 'not_ok', 'uncertain', 'estimate', 'approve', 'reject')),
                summary        TEXT NOT NULL CHECK (length(trim(summary)) > 0),
                sources        TEXT NOT NULL CHECK (json_valid(sources)),
                net_minor      INTEGER,
                currency       TEXT,
                at             TEXT NOT NULL,
                CHECK ((net_minor IS NULL) = (currency IS NULL))
            ) STRICT
            """,
            """
            CREATE TRIGGER opportunity_steps_no_update BEFORE UPDATE ON opportunity_steps
            BEGIN SELECT RAISE(ABORT, 'opportunity_steps är append-only'); END
            """,
            """
            CREATE TRIGGER opportunity_steps_no_delete BEFORE DELETE ON opportunity_steps
            BEGIN SELECT RAISE(ABORT, 'opportunity_steps är append-only'); END
            """,
        ),
    ),
    Migration(
        version=15,
        name="stop_loss",
        statements=(
            # Fas 4e-1 (ER-13, §26, D-029): stop-loss (Yorgo). En utlösning raderas aldrig och ändras aldrig.
            # Den är aktiv tills två olika grundare har godkänt en återhämtningsplan (stop_loss_votes).
            """
            CREATE TABLE stop_loss_trips (
                trip_id     INTEGER PRIMARY KEY,
                scope_kind  TEXT NOT NULL CHECK (scope_kind IN ('company', 'department', 'initiative')),
                scope_value TEXT NOT NULL,
                limit_name  TEXT NOT NULL,
                measured    TEXT NOT NULL,
                limit_value TEXT NOT NULL,
                currency    TEXT NOT NULL,
                exposure    TEXT NOT NULL CHECK (json_valid(exposure)),
                notified    TEXT NOT NULL CHECK (json_valid(notified)),
                tripped_at  TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER stop_loss_trips_no_update BEFORE UPDATE ON stop_loss_trips
            BEGIN SELECT RAISE(ABORT, 'en stop-loss-utlösning ändras aldrig'); END
            """,
            """
            CREATE TRIGGER stop_loss_trips_no_delete BEFORE DELETE ON stop_loss_trips
            BEGIN SELECT RAISE(ABORT, 'en stop-loss-utlösning raderas aldrig'); END
            """,
            """
            CREATE TABLE stop_loss_votes (
                id      INTEGER PRIMARY KEY,
                trip_id INTEGER NOT NULL REFERENCES stop_loss_trips (trip_id),
                founder TEXT NOT NULL,
                plan    TEXT NOT NULL CHECK (length(trim(plan)) > 0),
                at      TEXT NOT NULL,
                UNIQUE (trip_id, founder)
            ) STRICT
            """,
            """
            CREATE TRIGGER stop_loss_votes_no_update BEFORE UPDATE ON stop_loss_votes
            BEGIN SELECT RAISE(ABORT, 'stop_loss_votes är append-only'); END
            """,
            """
            CREATE TRIGGER stop_loss_votes_no_delete BEFORE DELETE ON stop_loss_votes
            BEGIN SELECT RAISE(ABORT, 'stop_loss_votes är append-only'); END
            """,
        ),
    ),
    Migration(
        version=16,
        name="kill_switch",
        statements=(
            # Fas 4e-2 (SR-07, §38, D-030): nödstoppet (Yorgo). Bara händelser, append-only. Läget är
            # den senaste av engaged/released; en återstart kräver två grundares release_vote efter engaged.
            """
            CREATE TABLE kill_switch_events (
                id     INTEGER PRIMARY KEY,
                event  TEXT NOT NULL CHECK (event IN ('engaged', 'release_vote', 'released')),
                actor  TEXT NOT NULL,
                reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
                at     TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER kill_switch_events_no_update BEFORE UPDATE ON kill_switch_events
            BEGIN SELECT RAISE(ABORT, 'nödstoppets händelser ändras aldrig'); END
            """,
            """
            CREATE TRIGGER kill_switch_events_no_delete BEFORE DELETE ON kill_switch_events
            BEGIN SELECT RAISE(ABORT, 'nödstoppets händelser raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=17,
        name="operating_mode",
        statements=(
            # Fas 4e-3 (SR-08, §59, D-031): skyddat driftläge (Yorgo). Bara händelser, append-only.
            # Läget är skyddat från 'entered' till nästa 'exited'. 'incident' är en anmäld säkerhetsincident.
            """
            CREATE TABLE operating_mode_events (
                id      INTEGER PRIMARY KEY,
                event   TEXT NOT NULL CHECK (event IN ('entered', 'incident', 'exited')),
                actor   TEXT NOT NULL,
                reasons TEXT NOT NULL CHECK (json_valid(reasons) AND json_array_length(reasons) > 0),
                at      TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER operating_mode_events_no_update BEFORE UPDATE ON operating_mode_events
            BEGIN SELECT RAISE(ABORT, 'driftlägets händelser ändras aldrig'); END
            """,
            """
            CREATE TRIGGER operating_mode_events_no_delete BEFORE DELETE ON operating_mode_events
            BEGIN SELECT RAISE(ABORT, 'driftlägets händelser raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=18,
        name="incidents",
        statements=(
            # Fas 5a (FR-15, §28, D-035): incidentrapporter (Yorgo). Reserverad som 20, numrerad om till 18
            # eftersom Tax Engine (18–19) inte hade börjat; se TODO.md. Kärnan ändras aldrig. Fälten är
            # append-only poster; en rättelse är en ny post som pekar på den gamla (corrects).
            """
            CREATE TABLE incidents (
                incident_id INTEGER PRIMARY KEY,
                source      TEXT NOT NULL UNIQUE,
                title       TEXT NOT NULL CHECK (length(trim(title)) > 0),
                reported_by TEXT NOT NULL,
                opened_at   TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER incidents_no_update BEFORE UPDATE ON incidents
            BEGIN SELECT RAISE(ABORT, 'en incident skrivs aldrig om; lägg till en post'); END
            """,
            """
            CREATE TRIGGER incidents_no_delete BEFORE DELETE ON incidents
            BEGIN SELECT RAISE(ABORT, 'incidenter raderas aldrig'); END
            """,
            """
            CREATE TABLE incident_entries (
                id          INTEGER PRIMARY KEY,
                incident_id INTEGER NOT NULL REFERENCES incidents (incident_id),
                field       TEXT NOT NULL,
                value       TEXT NOT NULL CHECK (json_valid(value)),
                actor       TEXT NOT NULL,
                corrects    INTEGER REFERENCES incident_entries (id),
                at          TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER incident_entries_no_update BEFORE UPDATE ON incident_entries
            BEGIN SELECT RAISE(ABORT, 'incidentposter är append-only; gör en rättelse'); END
            """,
            """
            CREATE TRIGGER incident_entries_no_delete BEFORE DELETE ON incident_entries
            BEGIN SELECT RAISE(ABORT, 'incidentposter raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=19,
        name="forecasts",
        statements=(
            # Fas 5b (FR-16, §20 steg 10, D-036): prognoslogg (Yorgo). Reserverad som 21, numrerad om till 19;
            # se TODO.md. En prognos ändras aldrig. En ny bedömning är en ny prognos som pekar på den gamla
            # (revises). Utfall är append-only; en rättelse pekar på det gamla utfallet (corrects).
            """
            CREATE TABLE forecasts (
                forecast_id INTEGER PRIMARY KEY,
                agent       TEXT NOT NULL,
                subject     TEXT NOT NULL CHECK (length(trim(subject)) > 0),
                metric      TEXT NOT NULL CHECK (metric IN ('net', 'revenue', 'costs', 'count')),
                unit        TEXT NOT NULL,
                expected    INTEGER NOT NULL,
                low         INTEGER,
                high        INTEGER,
                initiative  TEXT,
                decision    TEXT,
                due         TEXT NOT NULL,
                revises     INTEGER REFERENCES forecasts (forecast_id),
                made_at     TEXT NOT NULL,
                CHECK (low IS NULL OR low <= expected),
                CHECK (high IS NULL OR high >= expected),
                CHECK (metric = 'count' OR initiative IS NOT NULL)
            ) STRICT
            """,
            """
            CREATE TRIGGER forecasts_no_update BEFORE UPDATE ON forecasts
            BEGIN SELECT RAISE(ABORT, 'en prognos skrivs aldrig om; gör en ny som pekar på den gamla'); END
            """,
            """
            CREATE TRIGGER forecasts_no_delete BEFORE DELETE ON forecasts
            BEGIN SELECT RAISE(ABORT, 'prognoser raderas aldrig'); END
            """,
            """
            CREATE TABLE forecast_outcomes (
                id          INTEGER PRIMARY KEY,
                forecast_id INTEGER NOT NULL REFERENCES forecasts (forecast_id),
                actual      INTEGER NOT NULL,
                source      TEXT NOT NULL CHECK (source IN ('ledger', 'manual')),
                evidence    TEXT NOT NULL CHECK (json_valid(evidence)),
                note        TEXT NOT NULL,
                actor       TEXT NOT NULL,
                corrects    INTEGER REFERENCES forecast_outcomes (id),
                at          TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER forecast_outcomes_no_update BEFORE UPDATE ON forecast_outcomes
            BEGIN SELECT RAISE(ABORT, 'utfall är append-only; gör en rättelse'); END
            """,
            """
            CREATE TRIGGER forecast_outcomes_no_delete BEFORE DELETE ON forecast_outcomes
            BEGIN SELECT RAISE(ABORT, 'utfall raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=20,
        name="performance_reviews",
        statements=(
            # Fas 5c (FR-19, §31, D-037): sparade prestationsbedömningar (Yorgo). Reserverad som 22, numrerad
            # om till 20; se TODO.md. En bedömning är en ögonblicksbild med underlag och ändras aldrig.
            """
            CREATE TABLE performance_reviews (
                review_id   INTEGER PRIMARY KEY,
                agent_id    TEXT NOT NULL,
                role        TEXT NOT NULL,
                reviewer    TEXT NOT NULL,
                scorecard   TEXT NOT NULL CHECK (json_valid(scorecard)),
                note        TEXT NOT NULL,
                at          TEXT NOT NULL,
                CHECK (reviewer <> agent_id)
            ) STRICT
            """,
            """
            CREATE TRIGGER performance_reviews_no_update BEFORE UPDATE ON performance_reviews
            BEGIN SELECT RAISE(ABORT, 'en bedömning skrivs aldrig om; gör en ny'); END
            """,
            """
            CREATE TRIGGER performance_reviews_no_delete BEFORE DELETE ON performance_reviews
            BEGIN SELECT RAISE(ABORT, 'bedömningar raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=21,
        name="tax_assignments",
        statements=(
            # Fas 4f (ER-18, D-010, D-032): skattespår per intäkt. Robins nummer, använt av Yorgo vid
            # överlämningen 2026-10-26. En ändring av spåret är en ny rad som pekar på den gamla (corrects).
            """
            CREATE TABLE tax_assignments (
                id        INTEGER PRIMARY KEY,
                entry_id  INTEGER NOT NULL REFERENCES ledger_entries (entry_id),
                track     TEXT NOT NULL CHECK (track IN ('isk', 'self_employment', 'partnership', 'hobby')),
                owners    TEXT NOT NULL CHECK (json_valid(owners)),
                actor     TEXT NOT NULL,
                note      TEXT NOT NULL,
                corrects  INTEGER REFERENCES tax_assignments (id),
                at        TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER tax_assignments_no_update BEFORE UPDATE ON tax_assignments
            BEGIN SELECT RAISE(ABORT, 'skattespår skrivs aldrig om; gör en rättelse'); END
            """,
            """
            CREATE TRIGGER tax_assignments_no_delete BEFORE DELETE ON tax_assignments
            BEGIN SELECT RAISE(ABORT, 'skattespår raderas aldrig (ER-21)'); END
            """,
        ),
    ),
    Migration(
        version=22,
        name="tax_events",
        statements=(
            # Fas 4f (ER-20, ER-21, D-033, D-034): momsgränsen och exporterade deklarationsunderlag.
            """
            CREATE TABLE tax_events (
                id       INTEGER PRIMARY KEY,
                event    TEXT NOT NULL CHECK (event IN ('vat_warning', 'vat_limit', 'vat_vote', 'vat_decided', 'export')),
                year     INTEGER NOT NULL,
                actor    TEXT NOT NULL,
                details  TEXT NOT NULL CHECK (json_valid(details)),
                at       TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER tax_events_no_update BEFORE UPDATE ON tax_events
            BEGIN SELECT RAISE(ABORT, 'skattehändelser är append-only'); END
            """,
            """
            CREATE TRIGGER tax_events_no_delete BEFORE DELETE ON tax_events
            BEGIN SELECT RAISE(ABORT, 'skattehändelser raderas aldrig (ER-21)'); END
            """,
        ),
    ),
    Migration(
        version=23,
        name="lessons",
        statements=(
            # Fas 5d (FR-17, §29, D-038): lärdomsregister (Robins uppgift, gjord av Yorgo vid överlämningen
            # 2026-10-26). En lärdom skrivs aldrig om; statusen ändras genom händelser.
            """
            CREATE TABLE lessons (
                lesson_id   INTEGER PRIMARY KEY,
                statement   TEXT NOT NULL CHECK (length(trim(statement)) > 0),
                cause       TEXT NOT NULL CHECK (cause IN ('random', 'predictable_error', 'bad_information',
                            'bad_execution', 'bad_strategy', 'market_change', 'insufficient_data')),
                scope       TEXT NOT NULL,
                sources     TEXT NOT NULL CHECK (json_valid(sources)),
                proposed_by TEXT NOT NULL,
                at          TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER lessons_no_update BEFORE UPDATE ON lessons
            BEGIN SELECT RAISE(ABORT, 'en lärdom skrivs aldrig om; lägg till en händelse'); END
            """,
            """
            CREATE TRIGGER lessons_no_delete BEFORE DELETE ON lessons
            BEGIN SELECT RAISE(ABORT, 'lärdomar raderas aldrig'); END
            """,
            """
            CREATE TABLE lesson_events (
                id        INTEGER PRIMARY KEY,
                lesson_id INTEGER NOT NULL REFERENCES lessons (lesson_id),
                event     TEXT NOT NULL CHECK (event IN ('evidence', 'promote', 'rule_vote', 'demote', 'reject')),
                status    TEXT,
                actor     TEXT NOT NULL,
                note      TEXT NOT NULL,
                evidence  TEXT NOT NULL CHECK (json_valid(evidence)),
                at        TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER lesson_events_no_update BEFORE UPDATE ON lesson_events
            BEGIN SELECT RAISE(ABORT, 'lärdomshändelser är append-only'); END
            """,
            """
            CREATE TRIGGER lesson_events_no_delete BEFORE DELETE ON lesson_events
            BEGIN SELECT RAISE(ABORT, 'lärdomshändelser raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=24,
        name="strategy_versions",
        statements=(
            # Fas 5e (FR-18, §53, D-039): versionerade strategier och agentversioner (Robins uppgift, gjord av
            # Yorgo vid överlämningen 2026-10-26). En återställning är en ny version som pekar på den gamla.
            """
            CREATE TABLE strategy_versions (
                id         INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                kind       TEXT NOT NULL CHECK (kind IN ('strategy', 'agent')),
                version    INTEGER NOT NULL CHECK (version >= 1),
                content    TEXT NOT NULL CHECK (json_valid(content)),
                reason     TEXT NOT NULL CHECK (length(trim(reason)) > 0),
                lessons    TEXT NOT NULL CHECK (json_valid(lessons)),
                mandatory  INTEGER NOT NULL CHECK (mandatory IN (0, 1)),
                restores   INTEGER REFERENCES strategy_versions (id),
                author     TEXT NOT NULL,
                at         TEXT NOT NULL,
                UNIQUE (name, version)
            ) STRICT
            """,
            """
            CREATE TRIGGER strategy_versions_no_update BEFORE UPDATE ON strategy_versions
            BEGIN SELECT RAISE(ABORT, 'en version skrivs aldrig om; gör en ny'); END
            """,
            """
            CREATE TRIGGER strategy_versions_no_delete BEFORE DELETE ON strategy_versions
            BEGIN SELECT RAISE(ABORT, 'versioner raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=25,
        name="removal_cases",
        statements=(
            # Fas 5f (SR-17, §33, D-040): ärenden om avstängning och avveckling (Robins uppgift, gjord av
            # Yorgo vid överlämningen 2026-10-26). Ärenden och händelser är append-only.
            """
            CREATE TABLE removal_cases (
                case_id   INTEGER PRIMARY KEY,
                agent_id  TEXT NOT NULL REFERENCES agents (agent_id),
                target    TEXT NOT NULL CHECK (target IN ('SUSPENDED', 'RETIRED')),
                criteria  TEXT NOT NULL CHECK (json_valid(criteria)),
                evidence  TEXT NOT NULL CHECK (json_valid(evidence)),
                note      TEXT NOT NULL CHECK (length(trim(note)) > 0),
                opened_by TEXT NOT NULL,
                at        TEXT NOT NULL,
                CHECK (opened_by <> agent_id)
            ) STRICT
            """,
            """
            CREATE TRIGGER removal_cases_no_update BEFORE UPDATE ON removal_cases
            BEGIN SELECT RAISE(ABORT, 'ett ärende skrivs aldrig om; lägg till en händelse'); END
            """,
            """
            CREATE TRIGGER removal_cases_no_delete BEFORE DELETE ON removal_cases
            BEGIN SELECT RAISE(ABORT, 'ärenden raderas aldrig'); END
            """,
            """
            CREATE TABLE removal_events (
                id       INTEGER PRIMARY KEY,
                case_id  INTEGER NOT NULL REFERENCES removal_cases (case_id),
                event    TEXT NOT NULL CHECK (event IN ('response', 'vote', 'dismissed', 'approved', 'executed')),
                actor    TEXT NOT NULL,
                note     TEXT NOT NULL,
                at       TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER removal_events_no_update BEFORE UPDATE ON removal_events
            BEGIN SELECT RAISE(ABORT, 'ärendehändelser är append-only'); END
            """,
            """
            CREATE TRIGGER removal_events_no_delete BEFORE DELETE ON removal_events
            BEGIN SELECT RAISE(ABORT, 'ärendehändelser raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=26,
        name="simulation",
        statements=(
            # Fas 6b-1 (FR-20, §54, D-042): simuleringskörningar och simulerade dagar (Yorgo). En körning per
            # databas. Dagarna är append-only, så att en körning kan återupptas efter omstart utan att något
            # skrivs om.
            """
            CREATE TABLE simulation_runs (
                run_id     INTEGER PRIMARY KEY,
                scenario   TEXT NOT NULL,
                seed       TEXT NOT NULL,
                days       INTEGER NOT NULL CHECK (days >= 1),
                start_date TEXT NOT NULL,
                definition TEXT NOT NULL CHECK (json_valid(definition)),
                created_by TEXT NOT NULL,
                at         TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER simulation_runs_no_update BEFORE UPDATE ON simulation_runs
            BEGIN SELECT RAISE(ABORT, 'en simuleringskörning skrivs aldrig om'); END
            """,
            """
            CREATE TRIGGER simulation_runs_no_delete BEFORE DELETE ON simulation_runs
            BEGIN SELECT RAISE(ABORT, 'simuleringskörningar raderas aldrig'); END
            """,
            """
            CREATE TABLE simulation_days (
                id       INTEGER PRIMARY KEY,
                run_id   INTEGER NOT NULL REFERENCES simulation_runs (run_id),
                day      INTEGER NOT NULL CHECK (day >= 1),
                date     TEXT NOT NULL,
                summary  TEXT NOT NULL CHECK (json_valid(summary)),
                at       TEXT NOT NULL,
                UNIQUE (run_id, day)
            ) STRICT
            """,
            """
            CREATE TRIGGER simulation_days_no_update BEFORE UPDATE ON simulation_days
            BEGIN SELECT RAISE(ABORT, 'en simulerad dag skrivs aldrig om'); END
            """,
            """
            CREATE TRIGGER simulation_days_no_delete BEFORE DELETE ON simulation_days
            BEGIN SELECT RAISE(ABORT, 'simulerade dagar raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=27,
        name="tax_payment",
        statements=(
            # F3 (arbetsorder 02, D-052): posttypen tax_payment i ledgern och kopplingen till spår och år.
            # Reserverad för 6b-4 men använd här, eftersom migrationerna måste vara 1..N utan luckor (TODO.md).
            #
            # SQLite kan inte ändra en CHECK. Tabellen återskapas därför enligt SQLites dokumenterade sätt
            # för en föräldratabell, i en enda transaktion:
            # 1. Kontrollen av främmande nycklar skjuts upp till commit (defer_foreign_keys).
            # 2. Raderna kopieras till en arbetstabell, och den gamla tabellen tas bort.
            # 3. En ny ledger_entries med tax_payment i listan skapas, och raderna läggs tillbaka i samma
            #    ordning med samma entry_id. Vid commit pekar ledger_status, tax_assignments och
            #    rättelser åter på giltiga poster. Annars rullas allt tillbaka.
            # 4. Spärrarna mot ändring och radering återskapas (ER-08). Inget i ledgern ändras eller förloras.
            "PRAGMA defer_foreign_keys = ON",
            "CREATE TABLE ledger_entries_copy_27 AS SELECT * FROM ledger_entries",
            "DROP TRIGGER ledger_entries_no_update",
            "DROP TRIGGER ledger_entries_no_delete",
            "DROP TABLE ledger_entries",
            """
            CREATE TABLE ledger_entries (
                entry_id        INTEGER PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE CHECK (length(trim(idempotency_key)) > 0),
                recorded_at     TEXT NOT NULL,
                recorded_by     TEXT NOT NULL CHECK (length(trim(recorded_by)) > 0),
                department      TEXT NOT NULL CHECK (length(trim(department)) > 0),
                amount_minor    INTEGER NOT NULL CHECK (amount_minor != 0),
                currency        TEXT NOT NULL CHECK (length(currency) = 3 AND currency = upper(currency)),
                entry_type      TEXT NOT NULL CHECK (entry_type IN
                                ('revenue', 'cost', 'fee', 'refund', 'capital_in', 'capital_out', 'tax_payment')),
                initiative      TEXT NOT NULL CHECK (length(trim(initiative)) > 0),
                approval_status TEXT NOT NULL CHECK (approval_status IN ('not_required', 'approved', 'unapproved')),
                evidence        TEXT NOT NULL CHECK (json_valid(evidence) AND json_array_length(evidence) > 0),
                external_id     TEXT UNIQUE,
                corrects        INTEGER REFERENCES ledger_entries (entry_id),
                note            TEXT NOT NULL,
                CHECK (amount_minor > 0 OR corrects IS NOT NULL)
            ) STRICT
            """,
            "INSERT INTO ledger_entries SELECT * FROM ledger_entries_copy_27 ORDER BY entry_id",
            "DROP TABLE ledger_entries_copy_27",
            """
            CREATE TRIGGER ledger_entries_no_update BEFORE UPDATE ON ledger_entries
            BEGIN SELECT RAISE(ABORT, 'ledgerposter ändras aldrig; gör en korrigeringspost (ER-08)'); END
            """,
            """
            CREATE TRIGGER ledger_entries_no_delete BEFORE DELETE ON ledger_entries
            BEGIN SELECT RAISE(ABORT, 'ledgerposter raderas aldrig (ER-08)'); END
            """,
            """
            CREATE TABLE tax_payments (
                id        INTEGER PRIMARY KEY,
                entry_id  INTEGER NOT NULL UNIQUE REFERENCES ledger_entries (entry_id),
                track     TEXT CHECK (track IS NULL OR track IN ('isk', 'self_employment', 'partnership', 'hobby')),
                year      INTEGER NOT NULL CHECK (year BETWEEN 2000 AND 2999),
                actor     TEXT NOT NULL,
                at        TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER tax_payments_no_update BEFORE UPDATE ON tax_payments
            BEGIN SELECT RAISE(ABORT, 'skattebetalningar ändras aldrig; rätta med en korrigeringspost'); END
            """,
            """
            CREATE TRIGGER tax_payments_no_delete BEFORE DELETE ON tax_payments
            BEGIN SELECT RAISE(ABORT, 'skattebetalningar raderas aldrig (ER-21)'); END
            """,
        ),
    ),
    Migration(
        version=28,
        name="spend_approvals",
        statements=(
            # F5 (arbetsorder 02, D-053): godkännanden för enskilda utgifter. En förfrågan gäller ett
            # departement, ett initiativ och ett högsta belopp. Händelserna är append-only, och de unika
            # indexen gör att en förfrågan får högst ett beslut och förbrukas högst en gång, även vid
            # samtidiga försök.
            """
            CREATE TABLE spend_approvals (
                approval_id  INTEGER PRIMARY KEY,
                department   TEXT NOT NULL,
                initiative   TEXT NOT NULL CHECK (length(trim(initiative)) > 0),
                amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
                currency     TEXT NOT NULL CHECK (length(currency) = 3),
                requested_by TEXT NOT NULL,
                reason       TEXT NOT NULL CHECK (length(trim(reason)) > 0),
                at           TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TRIGGER spend_approvals_no_update BEFORE UPDATE ON spend_approvals
            BEGIN SELECT RAISE(ABORT, 'en förfrågan skrivs aldrig om; gör en ny'); END
            """,
            """
            CREATE TRIGGER spend_approvals_no_delete BEFORE DELETE ON spend_approvals
            BEGIN SELECT RAISE(ABORT, 'förfrågningar raderas aldrig'); END
            """,
            """
            CREATE TABLE spend_approval_events (
                id          INTEGER PRIMARY KEY,
                approval_id INTEGER NOT NULL REFERENCES spend_approvals (approval_id),
                event       TEXT NOT NULL CHECK (event IN ('approved', 'rejected', 'consumed')),
                decided     INTEGER GENERATED ALWAYS AS (CASE WHEN event IN ('approved', 'rejected') THEN 1 END) STORED,
                actor       TEXT NOT NULL,
                note        TEXT NOT NULL,
                entry_ref   TEXT,
                at          TEXT NOT NULL
            ) STRICT
            """,
            "CREATE UNIQUE INDEX spend_approval_one_decision ON spend_approval_events (approval_id) WHERE decided = 1",
            "CREATE UNIQUE INDEX spend_approval_used_once ON spend_approval_events (approval_id) WHERE event = 'consumed'",
            """
            CREATE TRIGGER spend_approval_events_no_update BEFORE UPDATE ON spend_approval_events
            BEGIN SELECT RAISE(ABORT, 'godkännandehändelser är append-only'); END
            """,
            """
            CREATE TRIGGER spend_approval_events_no_delete BEFORE DELETE ON spend_approval_events
            BEGIN SELECT RAISE(ABORT, 'godkännandehändelser raderas aldrig'); END
            """,
        ),
    ),
    Migration(
        version=29,
        name="registry",
        statements=(
            # PR 4 (arbetsorder 02, D-056): plattforms- och initiativregistret. Varje ändring är en ny
            # version; den senaste gäller. Inget skrivs om eller raderas.
            """
            CREATE TABLE registry_versions (
                id             INTEGER PRIMARY KEY,
                kind           TEXT NOT NULL CHECK (kind IN ('platform', 'initiative')),
                key            TEXT NOT NULL CHECK (length(trim(key)) > 0),
                version        INTEGER NOT NULL CHECK (version >= 1),
                status         TEXT NOT NULL CHECK (status IN
                               ('idea', 'investigated', 'reviewed', 'approved', 'active', 'paused', 'retired')),
                data           TEXT NOT NULL CHECK (json_valid(data)),
                actor          TEXT NOT NULL,
                note           TEXT NOT NULL,
                opportunity_id INTEGER REFERENCES opportunities (opportunity_id),
                at             TEXT NOT NULL,
                UNIQUE (kind, key, version)
            ) STRICT
            """,
            """
            CREATE TRIGGER registry_versions_no_update BEFORE UPDATE ON registry_versions
            BEGIN SELECT RAISE(ABORT, 'en version skrivs aldrig om; gör en ny'); END
            """,
            """
            CREATE TRIGGER registry_versions_no_delete BEFORE DELETE ON registry_versions
            BEGIN SELECT RAISE(ABORT, 'registerversioner raderas aldrig'); END
            """,
        ),
    ),
)

validate_migrations(MIGRATIONS)
