"""Godkännanden för enskilda utgifter (F5, D-053, D-049, ER-14).

En utgift över `HUMAN_APPROVAL_THRESHOLD` kräver en grundares godkännande (D-049). Förut gav
`BudgetEngine.check()` alltid nej över tröskeln, och godkännandekön var inte kopplad till budgetmotorn.
Därför kunde en godkänd utgift aldrig genomföras.

Flödet:
1. `request()`: en agent eller grundare begär en utgift för ett departement, ett initiativ och ett
   högsta belopp, med skäl. Det sparas append-only (migration 28).
2. `approve()` eller `reject()`: en grundare beslutar. En förfrågan får högst ett beslut.
3. `BudgetEngine.check(..., approval_id=N)` godtar godkännandet bara om alla villkor gäller:
   - förfrågan är godkänd och inte redan förbrukad
   - godkännandet är högst `VALID_DAYS` dagar gammalt
   - samma departement, samma initiativ och samma valuta
   - beloppet är högst det godkända
4. Godkännandet ersätter **bara** kravet på en grundare. Alla andra gränser gäller ändå: budgettak,
   reserv, `MAX_SINGLE_TRANSACTION`, stop-loss, nödstopp och skyddat driftläge. Hårda gränser kan
   aldrig godkännas bort (§21).
5. `BudgetEngine.record_spend()` förbrukar godkännandet i samma transaktion som utgiften. Ett unikt index gör att det förbrukas
   exakt en gång, även när två försök görs samtidigt. Det andra försöket får nej.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..audit import AuditLog
from ..memory import Database
from .config import Risk

VALID_DAYS = 7  # D-053


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SpendApprovalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SpendApproval:
    approval_id: int
    department: str
    initiative: str
    amount_minor: int
    currency: str
    requested_by: str
    reason: str
    at: str
    status: str  # pending | approved | rejected | consumed
    decided_by: str | None = None
    decided_at: str | None = None
    risk_class: str | None = None  # NULL for legacy requests: fail closed
    category: str | None = None


class SpendApprovals:
    def __init__(self, db: Database, audit: AuditLog, founders: frozenset[str],
                 clock: Callable[[], str] = _now) -> None:
        self._db = db
        self._audit = audit
        self._founders = frozenset(founders)
        self._clock = clock

    def request(self, actor: str, department: str, initiative: str, amount_minor: int, currency: str,
                reason: str, *, risk_class: Risk, category: str = "OPERATIONS") -> SpendApproval:
        if not isinstance(risk_class, Risk) or risk_class is Risk.CRITICAL or not category.strip():
            raise SpendApprovalError("ange tillåten riskklass och kategori")
        if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
            raise SpendApprovalError("beloppet ska vara ett heltal > 0 i minsta enhet (D-006)")
        if not reason.strip() or not initiative.strip() or not department.strip():
            raise SpendApprovalError("ange departement, initiativ och skäl")
        with self._db.transaction() as tx:
            approval_id = tx.execute(
                "INSERT INTO spend_approvals (department, initiative, amount_minor, currency, requested_by, reason, at, risk_class, category) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (department, initiative, amount_minor, currency, actor, reason, self._clock(), risk_class.value, category),
            ).lastrowid
        self._audit.append(actor, "spend_approval.requested",
                           {"approval_id": approval_id, "department": department, "initiative": initiative,
                            "amount_minor": amount_minor, "notify": ["founders"]})
        return self.get(approval_id)

    def approve(self, founder: str, approval_id: int, note: str) -> SpendApproval:
        return self._decide(founder, approval_id, "approved", note)

    def reject(self, founder: str, approval_id: int, note: str) -> SpendApproval:
        if not note.strip():
            raise SpendApprovalError("ett nej kräver en motivering")
        return self._decide(founder, approval_id, "rejected", note)

    def get(self, approval_id: int) -> SpendApproval | None:
        row = self._db.connection.execute(
            "SELECT approval_id, department, initiative, amount_minor, currency, requested_by, reason, at, risk_class, category "
            "FROM spend_approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        if row is None:
            return None
        events = self._db.connection.execute(
            "SELECT event, actor, at FROM spend_approval_events WHERE approval_id = ? ORDER BY id",
            (approval_id,)).fetchall()
        status, by, when = "pending", None, None
        for event, actor, at in events:
            if event in ("approved", "rejected"):
                status, by, when = event, actor, at
            elif event == "consumed":
                status = "consumed"
        return SpendApproval(*row[:8], status=status, decided_by=by, decided_at=when, risk_class=row[8], category=row[9])

    def pending(self) -> tuple[SpendApproval, ...]:
        ids = [r[0] for r in self._db.connection.execute("SELECT approval_id FROM spend_approvals ORDER BY approval_id")]
        return tuple(a for a in (self.get(i) for i in ids) if a.status == "pending")

    def approved_unused(self) -> tuple[SpendApproval, ...]:
        ids = [r[0] for r in self._db.connection.execute("SELECT approval_id FROM spend_approvals ORDER BY approval_id")]
        return tuple(a for a in (self.get(i) for i in ids) if a.status == "approved")

    def problems(self, approval_id: int, request, now: datetime) -> list[str]:
        """Skäl till att godkännandet inte gäller för `request`. Tom lista = det gäller."""
        a = self.get(approval_id)
        if a is None:
            return [f"godkännande {approval_id} finns inte"]
        if a.status != "approved":
            return [f"godkännande {approval_id} är {a.status}, inte godkänt och oanvänt (D-053)"]
        out = []
        if a.risk_class is None or a.risk_class != getattr(request.risk_class, "value", None) or a.category != request.category:
            out.append("godkännandets riskklass/kategori saknas eller stämmer inte; begär nytt godkännande")
        if now - datetime.fromisoformat(a.decided_at) > timedelta(days=VALID_DAYS):
            out.append(f"godkännande {approval_id} är äldre än {VALID_DAYS} dagar (D-053)")
        if a.department != request.department:
            out.append(f"godkännande {approval_id} gäller departementet {a.department}, inte {request.department}")
        if a.initiative != request.initiative:
            out.append(f"godkännande {approval_id} gäller initiativet {a.initiative}, inte {request.initiative}")
        if a.currency != request.currency:
            out.append(f"godkännande {approval_id} gäller valutan {a.currency}")
        if request.amount_minor > a.amount_minor:
            out.append(f"beloppet {request.amount_minor} är större än det godkända {a.amount_minor}")
        return out

    def consume(self, approval_id: int, actor: str, note: str) -> bool:
        """Förbrukar godkännandet en gång. False om det redan är förbrukat (även vid samtidiga försök)."""
        try:
            with self._db.transaction() as tx:
                tx.execute("INSERT INTO spend_approval_events (approval_id, event, actor, note, at) "
                           "VALUES (?, 'consumed', ?, ?, ?)", (approval_id, actor, note, self._clock()))
        except sqlite3.IntegrityError:
            return False
        self._audit.append(actor, "spend_approval.consumed", {"approval_id": approval_id, "note": note})
        return True

    def _decide(self, founder: str, approval_id: int, event: str, note: str) -> SpendApproval:
        if founder not in self._founders:
            raise SpendApprovalError("bara en grundare godkänner utgifter över tröskeln (D-049, ER-14)")
        a = self.get(approval_id)
        if a is None:
            raise SpendApprovalError(f"förfrågan {approval_id} finns inte")
        if a.status != "pending":
            raise SpendApprovalError(f"förfrågan {approval_id} är redan {a.status}")
        try:
            with self._db.transaction() as tx:
                tx.execute("INSERT INTO spend_approval_events (approval_id, event, actor, note, at) VALUES (?, ?, ?, ?, ?)",
                           (approval_id, event, founder, note, self._clock()))
        except sqlite3.IntegrityError:
            raise SpendApprovalError(f"förfrågan {approval_id} har redan ett beslut") from None
        self._audit.append(founder, f"spend_approval.{event}", {"approval_id": approval_id, "note": note})
        return self.get(approval_id)
