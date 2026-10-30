"""Ledgern (Fas 4a, §40): det ekonomiska registret. Allt som räknas om pengar räknas härifrån.

Varje post har §40:s tolv fält: ID, tidsstämpel, vem som registrerade, departement, belopp och
valuta, typ, affärsinitiativ, godkännandestatus, underlag, externt ID, slutlig status och
eventuell korrigering. Reglerna upprätthålls av koden och av databasen (migration 13):

- **Belopp** är heltal i minsta enhet med valuta (ER-01, D-006). Aldrig flyttal.
- **Sim och verkligt** hålls isär (ER-15, SR-11): i `sim` tas bara `SIM` emot, i `prod` aldrig `SIM`.
- **Dubbelregistrering** (ER-07, SR-12): varje post har en idempotensnyckel. Samma nyckel med
  samma innehåll ger tillbaka den befintliga posten; samma nyckel med annat innehåll, eller ett
  externt ID som redan finns, avvisas.
- **Inget skrivs om** (ER-08): poster ändras och raderas aldrig. Ett fel rättas med en
  korrigeringspost som pekar på originalet. Status går bara framåt: `pending` → `settled`,
  `failed` eller `cancelled`.
- **Fakta avvisas inte för att de är obekväma:** en kostnad som redan har skett registreras även
  om den saknar godkännande. Den märks `unapproved` och syns i resultatet som en avvikelse.
  Att stoppa en handling *innan* den sker är budgetmotorns uppgift (ER-03), inte ledgerns.
- **Vem får skriva:** grundarna och de systemkomponenter som uttryckligen anges (till exempel
  `system:payments`). Agenter skriver inte i ledgern i Fas 4a. **Läsa** får grundarna och agenter
  med `ledger.read` (CFO, Audit).

Varje registrering, statusändring, korrigering och avvisad dubblett skrivs till revisionsloggen.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum

from ..audit import AuditLog
from ..authorization import AuthorizationEngine
from ..config.models import SIM_CURRENCY
from ..memory import Database
from ..monitoring import mask_secrets

READ_TOOL = "ledger.read"
_EVIDENCE = re.compile(
    r"(ledger|task|audit|file|url|decision|report|approval|external):\S+"
)
_CURRENCY = re.compile(r"[A-Z]{3}")
_COMPONENT = re.compile(r"system:[a-z][a-z0-9_-]*")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class EntryType(str, Enum):
    REVENUE = "revenue"  # intäkt, brutto (ER-23)
    COST = "cost"
    FEE = "fee"  # plattformsavgift, separat post (ER-23)
    REFUND = "refund"  # återbetalning till kund; minskar intäkten
    CAPITAL_IN = "capital_in"  # insatt kapital; ingen intäkt
    CAPITAL_OUT = "capital_out"  # uttag; ingen kostnad
    TAX_PAYMENT = "tax_payment"  # betald skatt; minskar kassan och skatteavsättningen, ingen kostnad (D-052)


class Approval(str, Enum):
    NOT_REQUIRED = "not_required"
    APPROVED = (
        "approved"  # underlaget ska då peka på godkännandet (approval: eller decision:)
    )
    UNAPPROVED = "unapproved"  # skedde utan godkännande; flaggas i resultatet


class Status(str, Enum):
    PENDING = "pending"  # väntad; räknas aldrig som realiserad (ER-11)
    SETTLED = "settled"  # genomförd och mottagen eller betald
    FAILED = "failed"
    CANCELLED = "cancelled"


FINAL = frozenset({Status.SETTLED, Status.FAILED, Status.CANCELLED})
OUTGOING = frozenset({EntryType.COST, EntryType.FEE, EntryType.REFUND, EntryType.CAPITAL_OUT, EntryType.TAX_PAYMENT})


class LedgerError(ValueError):
    """Posten kunde inte registreras eller ändras. Meddelandet förklarar varför."""


class DuplicateEntry(LedgerError):
    def __init__(self, message: str, existing_entry_id: int) -> None:
        self.existing_entry_id = existing_entry_id
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class EntryDraft:
    idempotency_key: str
    department: str
    amount_minor: int
    currency: str
    entry_type: EntryType
    initiative: str
    approval: Approval
    evidence: tuple[str, ...]
    external_id: str | None = None
    status: Status = Status.PENDING
    note: str = ""
    occurred_on: str | None = None


@dataclass(frozen=True, slots=True)
class StatusEvent:
    status: Status
    actor: str
    note: str
    at: str


@dataclass(frozen=True, slots=True)
class Entry:
    entry_id: int
    idempotency_key: str
    recorded_at: str
    recorded_by: str
    department: str
    amount_minor: int
    currency: str
    entry_type: EntryType
    initiative: str
    approval: Approval
    evidence: tuple[str, ...]
    external_id: str | None
    corrects: int | None
    note: str
    status: Status
    history: tuple[StatusEvent, ...] = field(default=(), compare=False)
    occurred_on: str | None = None

    @property
    def economic_date(self) -> str:
        """Event date for financial periods; old records fall back to registration day."""
        return self.occurred_on or self.recorded_at[:10]


_COLUMNS = (
    "entry_id, idempotency_key, recorded_at, recorded_by, department, amount_minor, currency, "
    "entry_type, initiative, approval_status, evidence, external_id, corrects, note, occurred_on"
)


class Ledger:
    def __init__(
        self,
        db: Database,
        engine: AuthorizationEngine,
        departments: Iterable[str],
        founders: frozenset[str],
        audit: AuditLog,
        approval_threshold: int | None,
        components: frozenset[str] = frozenset(),
        clock: Callable[[], str] = _now,
    ) -> None:
        bad = [c for c in components if not _COMPONENT.fullmatch(c)]
        if bad:
            raise LedgerError(f"systemkomponenter måste heta system:<namn>, fick {bad}")
        self._db = db
        self._engine = engine
        self._departments = frozenset(departments)
        self._founders = frozenset(founders)
        self._audit = audit
        self._components = frozenset(components)
        self._threshold = approval_threshold
        self._clock = clock

    # --- Skriva ------------------------------------------------------------------------------

    def record(self, actor: str, draft: EntryDraft) -> Entry:
        self._require_writer(actor)
        errors = self._validate(draft)
        if errors:
            raise LedgerError("posten avvisas: " + "; ".join(errors))
        existing = self._by_key(draft.idempotency_key)
        if existing is not None:
            return self._replay(actor, existing, draft)
        if draft.external_id is not None:
            clash = self._db.connection.execute(
                "SELECT entry_id FROM ledger_entries WHERE external_id = ?",
                (draft.external_id,),
            ).fetchone()
            if clash:
                self._refuse_duplicate(actor, draft, clash[0], "externt ID finns redan")
        entry_id = self._insert(actor, draft, corrects=None)
        entry = self.get(entry_id)
        self._audit.append(actor, "ledger.recorded", self._summary(entry))
        return entry

    def set_status(self, actor: str, entry_id: int, status: Status, note: str) -> Entry:
        """Slutlig status (§40). Bara från `pending`; en slutlig status ändras aldrig."""
        self._require_writer(actor)
        entry = self.get(entry_id)
        if entry is None:
            raise LedgerError(f"post {entry_id} finns inte")
        if status not in FINAL:
            raise LedgerError("ny status måste vara settled, failed eller cancelled")
        if entry.status is not Status.PENDING:
            raise LedgerError(
                f"post {entry_id} är redan {entry.status.value}; gör en korrigeringspost (ER-08)"
            )
        if not note.strip() or mask_secrets(note) != note:
            raise LedgerError("en statusändring behöver en motivering utan hemligheter")
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO ledger_status (entry_id, status, actor, note, at) VALUES (?, ?, ?, ?, ?)",
                (entry_id, status.value, actor, note, self._clock()),
            )
        self._audit.append(
            actor, "ledger.status", {"entry_id": entry_id, "status": status.value}
        )
        return self.get(entry_id)

    def correct(
        self,
        actor: str,
        entry_id: int,
        amount_minor: int,
        reason: str,
        evidence: tuple[str, ...],
        idempotency_key: str,
    ) -> Entry:
        """Rättar en genomförd post med en ny post (ER-08). Originalet står kvar oförändrat."""
        self._require_writer(actor)
        original = self.get(entry_id)
        if original is None:
            raise LedgerError(f"post {entry_id} finns inte")
        if original.corrects is not None:
            raise LedgerError("rätta originalposten, inte en korrigering")
        if original.status is not Status.SETTLED:
            raise LedgerError(
                "bara genomförda poster rättas; en väntande post avbryts i stället (cancelled)"
            )
        if (
            isinstance(amount_minor, bool)
            or not isinstance(amount_minor, int)
            or amount_minor == 0
        ):
            raise LedgerError(
                "korrigeringen måste vara ett heltal skilt från 0 i minsta enhet (ER-01)"
            )
        corrected = (
            original.amount_minor
            + sum(c.amount_minor for c in self.corrections(entry_id))
            + amount_minor
        )
        if corrected < 0:
            raise LedgerError(
                f"korrigeringen gör posten negativ ({corrected}); registrera en återbetalning i stället"
            )
        draft = EntryDraft(
            idempotency_key,
            original.department,
            amount_minor,
            original.currency,
            original.entry_type,
            original.initiative,
            original.approval,
            tuple(evidence),
            None,
            Status.SETTLED,
            reason,
            occurred_on=original.economic_date,
        )
        errors = self._validate(draft, correction=True)
        if not reason.strip():
            errors.append("en korrigering behöver ett skäl")
        if errors:
            raise LedgerError("korrigeringen avvisas: " + "; ".join(errors))
        existing = self._by_key(idempotency_key)
        if existing is not None:
            if existing.corrects == entry_id and existing.amount_minor == amount_minor:
                return existing
            self._refuse_duplicate(
                actor, draft, existing.entry_id, "idempotensnyckeln används redan"
            )
        new_id = self._insert(actor, draft, corrects=entry_id)
        entry = self.get(new_id)
        self._audit.append(
            actor, "ledger.corrected", {**self._summary(entry), "corrects": entry_id}
        )
        return entry

    # --- Läsa --------------------------------------------------------------------------------

    def require_reader(self, actor: str) -> None:
        if actor not in self._founders:
            self._engine.require(actor, READ_TOOL)  # PermissionDenied, och loggat

    def get(self, entry_id: int) -> Entry | None:
        row = self._db.connection.execute(
            f"SELECT {_COLUMNS} FROM ledger_entries WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        return self._entry(row) if row else None

    def entries(self, currency: str | None = None) -> tuple[Entry, ...]:
        sql, args = f"SELECT {_COLUMNS} FROM ledger_entries", ()
        if currency is not None:
            sql, args = sql + " WHERE currency = ?", (currency,)
        rows = self._db.connection.execute(sql + " ORDER BY entry_id", args).fetchall()
        return tuple(self._entry(r) for r in rows)

    def corrections(self, entry_id: int) -> tuple[Entry, ...]:
        rows = self._db.connection.execute(
            f"SELECT {_COLUMNS} FROM ledger_entries WHERE corrects = ? ORDER BY entry_id",
            (entry_id,),
        ).fetchall()
        return tuple(self._entry(r) for r in rows)

    # --- Internt -----------------------------------------------------------------------------

    def _require_writer(self, actor: str) -> None:
        if actor in self._founders or actor in self._components:
            return
        self._audit.append(
            actor,
            "ledger.denied",
            {"reason": "bara grundare och angivna systemkomponenter skriver"},
        )
        raise LedgerError(
            f"{actor!r} får inte skriva i ledgern (bara grundarna och angivna systemkomponenter)"
        )

    def _validate(self, d: EntryDraft, correction: bool = False) -> list[str]:
        errors: list[str] = []
        if d.occurred_on is not None:
            try:
                if date.fromisoformat(d.occurred_on).isoformat() != d.occurred_on:
                    raise ValueError("noncanonical date")
            except (ValueError, TypeError):
                errors.append("occurred_on måste vara ett datum ÅÅÅÅ-MM-DD")
        if not isinstance(d.idempotency_key, str) or not d.idempotency_key.strip():
            errors.append("idempotensnyckel saknas (SR-12)")
        if d.department not in self._departments:
            errors.append(f"okänt departement {d.department!r}")
        if isinstance(d.amount_minor, bool) or not isinstance(d.amount_minor, int):
            errors.append("beloppet måste vara ett heltal i minsta enhet (ER-01)")
        elif not correction and d.amount_minor <= 0:
            errors.append("beloppet måste vara större än 0; typen anger riktningen")
        if not isinstance(d.currency, str) or not _CURRENCY.fullmatch(d.currency):
            errors.append("valutan måste vara tre stora bokstäver, t.ex. SEK eller SIM")
        elif self._db.environment == "sim" and d.currency != SIM_CURRENCY:
            errors.append(f"i sim tas bara {SIM_CURRENCY} emot (ER-15, SR-11)")
        elif self._db.environment != "sim" and d.currency == SIM_CURRENCY:
            errors.append(f"{SIM_CURRENCY} får aldrig registreras i prod (ER-15)")
        if not isinstance(d.entry_type, EntryType):
            errors.append("okänd posttyp")
        if not isinstance(d.initiative, str) or not d.initiative.strip():
            errors.append("affärsinitiativ saknas (§40)")
        if not isinstance(d.approval, Approval):
            errors.append("okänd godkännandestatus")
        evidence = tuple(d.evidence) if isinstance(d.evidence, (tuple, list)) else ()
        if not evidence:
            errors.append("underlag saknas (§40)")
        elif any(
            not isinstance(e, str) or not _EVIDENCE.fullmatch(e) for e in evidence
        ):
            errors.append(
                "underlag måste se ut som url:, file:, external:, approval:, decision:, task:, report:, audit: eller ledger:"
            )
        if d.approval is Approval.APPROVED and not any(
            e.startswith(("approval:", "decision:")) for e in evidence
        ):
            errors.append(
                "ett godkänt belopp måste peka på godkännandet (approval: eller decision:)"
            )
        if (
            d.approval is Approval.NOT_REQUIRED
            and d.entry_type in OUTGOING
            and isinstance(d.amount_minor, int)
            and (self._threshold is None or abs(d.amount_minor) > self._threshold)
        ):
            errors.append(
                "belopp över HUMAN_APPROVAL_THRESHOLD (eller när gränsen saknas) är approved eller unapproved, "
                "aldrig not_required (ER-14, ER-02)"
            )
        if d.external_id is not None and (
            not isinstance(d.external_id, str) or not d.external_id.strip()
        ):
            errors.append("externt ID får inte vara tomt")
        if not isinstance(d.status, Status) or (
            not correction and d.status not in (Status.PENDING, Status.SETTLED)
        ):
            errors.append("en ny post är pending eller settled")
        texts = [
            d.note,
            d.initiative,
            d.idempotency_key,
            *(e for e in evidence if isinstance(e, str)),
        ]
        if d.external_id:
            texts.append(d.external_id)
        if any(isinstance(t, str) and mask_secrets(t) != t for t in texts):
            errors.append("texten ser ut att innehålla en hemlighet (SR-10)")
        return errors

    def _by_key(self, key: str) -> Entry | None:
        row = self._db.connection.execute(
            f"SELECT {_COLUMNS} FROM ledger_entries WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return self._entry(row) if row else None

    def _replay(self, actor: str, existing: Entry, draft: EntryDraft) -> Entry:
        same = existing.corrects is None and (
            existing.department,
            existing.amount_minor,
            existing.currency,
            existing.entry_type,
            existing.initiative,
            existing.external_id,
            existing.occurred_on,
        ) == (
            draft.department,
            draft.amount_minor,
            draft.currency,
            draft.entry_type,
            draft.initiative,
            draft.external_id,
            draft.occurred_on,
        )
        if not same:
            self._refuse_duplicate(
                actor,
                draft,
                existing.entry_id,
                "idempotensnyckeln används redan för en annan post",
            )
        self._audit.append(actor, "ledger.replayed", {"entry_id": existing.entry_id})
        return existing

    def _refuse_duplicate(
        self, actor: str, draft: EntryDraft, existing_id: int, reason: str
    ) -> None:
        self._audit.append(
            actor,
            "ledger.duplicate_refused",
            {"existing_entry_id": existing_id, "reason": reason},
        )
        raise DuplicateEntry(
            f"dubbelregistrering avvisad: {reason} (post {existing_id}, ER-07)",
            existing_id,
        )

    def _insert(self, actor: str, d: EntryDraft, corrects: int | None) -> int:
        now = self._clock()
        try:
            with self._db.transaction() as tx:
                cursor = tx.execute(
                    "INSERT INTO ledger_entries (idempotency_key, recorded_at, recorded_by, department, amount_minor, "
                    "currency, entry_type, initiative, approval_status, evidence, external_id, corrects, note, occurred_on) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        d.idempotency_key,
                        now,
                        actor,
                        d.department,
                        d.amount_minor,
                        d.currency,
                        d.entry_type.value,
                        d.initiative,
                        d.approval.value,
                        json.dumps(list(d.evidence)),
                        d.external_id,
                        corrects,
                        d.note,
                        d.occurred_on,
                    ),
                )
                entry_id = cursor.lastrowid
                tx.execute(
                    "INSERT INTO ledger_status (entry_id, status, actor, note, at) VALUES (?, ?, ?, ?, ?)",
                    (entry_id, d.status.value, actor, "registrerad", now),
                )
        except (
            sqlite3.IntegrityError
        ) as exc:  # samtidig dubblett som hann före: databasen är sista spärren
            raise LedgerError(f"posten avvisades av databasen: {exc}") from exc
        return entry_id

    def _entry(self, row: tuple) -> Entry:
        history = tuple(
            StatusEvent(Status(s), a, n, at)
            for s, a, n, at in self._db.connection.execute(
                "SELECT status, actor, note, at FROM ledger_status WHERE entry_id = ? ORDER BY id",
                (row[0],),
            )
        )
        return Entry(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            EntryType(row[7]),
            row[8],
            Approval(row[9]),
            tuple(json.loads(row[10])),
            row[11],
            row[12],
            row[13],
            history[-1].status,
            history,
            occurred_on=row[14],
        )

    @staticmethod
    def _summary(entry: Entry) -> dict:
        return {
            "entry_id": entry.entry_id,
            "entry_type": entry.entry_type.value,
            "amount_minor": entry.amount_minor,
            "currency": entry.currency,
            "department": entry.department,
            "initiative": entry.initiative,
            "approval": entry.approval.value,
            "status": entry.status.value,
        }
