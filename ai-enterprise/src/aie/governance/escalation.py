"""Eskalering till grundarna: godkännandekön (Fas 3, FR-13, D-019, konstitutionen §8 och §21).

Hit kommer det som ingen agent, och ibland ingen ensam grundare, får avgöra själv:
- **Beslut utanför en agents mandat** (`PermissionDenied`), till exempel en arbetsagent som
  saknar `decision.record`. Upp till `HUMAN_APPROVAL_THRESHOLD` räcker en grundare (D-019 p. 1).
- **Beslut över `HUMAN_APPROVAL_THRESHOLD`** (`NeedsApproval`). Båda grundarna krävs (D-019 p. 2).
- **Tvister eskalerade till grundarna** (§21). Över gränsen krävs båda.
- **Styrfrågor**: ändringar i konstitution, riskgränser eller mandat. Kräver alltid båda (D-019 p. 3).

Varje förfrågan sparas i `approval_requests` (migration 12) med beloppet, skälet och hur många
grundare som krävs. Rösterna sparas i `approval_votes`, en per grundare. Ett nej från en grundare
avslår förfrågan. När tillräckligt många har sagt ja genomförs den: beslutet loggas i
beslutsloggen eller tvisten avgörs. Allt revideras. Hårda gränser kan aldrig godkännas bort (§21).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum

from ..agents import AgentRegistry
from ..audit import AuditLog
from ..authorization import PermissionDenied
from ..config import RiskLimits
from ..memory import Database
from ..monitoring import mask_secrets
from .decisions import (
    Decision,
    DecisionDraft,
    DecisionError,
    DecisionLog,
    NeedsApproval,
    RiskClass,
)
from .disputes import (
    DisputeBoard,
    DisputeStatus,
    HardLimitViolation,
    Level,
    hard_limit_violations,
)


class RequestKind(str, Enum):
    DECISION = "decision"
    DISPUTE = "dispute"
    GOVERNANCE = "governance"


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Vote:
    founder: str
    verdict: str  # "approve" eller "reject"
    note: str
    at: str


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request_id: int
    kind: RequestKind
    task_id: int
    dispute_id: int | None
    requested_by: str
    reason: str
    amount_minor: int
    currency: str
    required_approvals: int
    status: RequestStatus
    outcome_decision: int | None
    votes: tuple[Vote, ...]

    @property
    def approvals(self) -> tuple[str, ...]:
        return tuple(v.founder for v in self.votes if v.verdict == "approve")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ApprovalQueue:
    def __init__(
        self,
        db: Database,
        decisions: DecisionLog,
        disputes: DisputeBoard,
        registry: AgentRegistry,
        limits: RiskLimits,
        founders: frozenset[str],
        audit: AuditLog,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        if len(founders) < 2:
            raise ApprovalError(
                "godkännandekön behöver båda grundarna i `founders` (D-019, D-021)"
            )
        self._db = db
        self._decisions = decisions
        self._disputes = disputes
        self._registry = registry
        self._limits = limits
        self._founders = frozenset(founders)
        self._audit = audit
        self._clock = clock

    # --- In i kön ----------------------------------------------------------------------------

    def submit_decision(
        self, actor: str, task_id: int, draft: DecisionDraft
    ) -> Decision | ApprovalRequest:
        """Fattar beslutet om `actor` får; annars hamnar det i kön. Returnerar beslutet eller förfrågan."""
        try:
            return self._decisions.record(actor, task_id, draft)
        except NeedsApproval as exc:
            reason = exc.reason
        except PermissionDenied as exc:  # utanför mandatet; nekandet är redan reviderat
            if actor not in self._founders and self._registry.get(actor) is None:
                raise
            reason = f"utanför mandatet: {exc}"
            self._decisions.check_task(task_id)
            self._decisions.validate(
                draft, task_id
            )  # ett ofullständigt beslut köas inte
        return self._enqueue(
            RequestKind.DECISION,
            actor,
            task_id,
            None,
            reason,
            draft.budget_minor,
            _draft_json(draft),
        )

    def submit_dispute(self, actor: str, dispute_id: int) -> ApprovalRequest:
        """Lägger en tvist som är eskalerad till grundarna i kön (§21)."""
        dispute = self._disputes.get(dispute_id)
        if (
            dispute is None
            or dispute.status is not DisputeStatus.ESCALATED
            or dispute.escalated_to is not Level.FOUNDERS
        ):
            raise ApprovalError(f"tvist {dispute_id} är inte eskalerad till grundarna")
        if self._pending_for_dispute(dispute_id):
            raise ApprovalError(f"tvist {dispute_id} ligger redan i kön")
        violations = hard_limit_violations(
            self._limits, dispute.proposal_budget, dispute.proposal_risk_class
        )
        reason = f"tvist om: {dispute.proposal}" + (
            f" (bryter mot hårda gränser: {'; '.join(violations)})"
            if violations
            else ""
        )
        return self._enqueue(
            RequestKind.DISPUTE,
            actor,
            dispute.task_id,
            dispute_id,
            reason,
            dispute.proposal_budget,
            "{}",
        )

    def submit_governance(
        self, actor: str, task_id: int, change: str
    ) -> ApprovalRequest:
        """Ändring i konstitution, riskgränser eller mandat. Kräver alltid båda grundarna (D-019 p. 3)."""
        if not change.strip() or mask_secrets(change) != change:
            raise ApprovalError("beskriv ändringen utan hemligheter")
        return self._enqueue(
            RequestKind.GOVERNANCE,
            actor,
            task_id,
            None,
            change.strip(),
            0,
            "{}",
            required=2,
        )

    # --- Grundarnas beslut --------------------------------------------------------------------

    def approve(self, founder: str, request_id: int, note: str = "") -> ApprovalRequest:
        current = self.get(request_id)
        if current is not None and current.kind is RequestKind.DISPUTE:
            violations = self._dispute_violations(current)
            if (
                violations
            ):  # §21: ingen ja-röst räknas; bara avslag eller ändrad gräns (D-019 p. 3)
                self._audit.append(
                    founder,
                    "approval.hard_limit_blocked",
                    {"request_id": request_id, "violations": violations},
                )
                raise HardLimitViolation(current.dispute_id, violations)
        request = self._vote(founder, request_id, "approve", note)
        if len(request.approvals) < request.required_approvals:
            return request  # väntar på den andra grundaren
        outcome = None
        if request.kind is RequestKind.DECISION:
            draft = _draft_from_json(self._payload(request_id))
            outcome = self._decisions.record_approved(
                request.approvals, request.task_id, draft
            ).decision_id
        elif request.kind is RequestKind.DISPUTE:
            self._disputes.resolve_approved(
                request.approvals,
                request.dispute_id,
                True,
                note or "godkänt av grundarna",
            )
        return self._finish(request, RequestStatus.APPROVED, outcome, founder)

    def reject(self, founder: str, request_id: int, note: str) -> ApprovalRequest:
        """Ett nej från en grundare räcker för att avslå (D-019)."""
        if not note.strip():
            raise ApprovalError("ett avslag kräver en motivering")
        request = self._vote(founder, request_id, "reject", note)
        if request.kind is RequestKind.DISPUTE:
            self._disputes.resolve_approved([founder], request.dispute_id, False, note)
        return self._finish(request, RequestStatus.REJECTED, None, founder)

    # --- Frågor ------------------------------------------------------------------------------

    def pending(self) -> tuple[ApprovalRequest, ...]:
        ids = self._db.connection.execute(
            "SELECT request_id FROM approval_requests WHERE status = 'pending' ORDER BY request_id"
        )
        return tuple(self.get(i) for (i,) in ids)

    def get(self, request_id: int) -> ApprovalRequest | None:
        conn = self._db.connection
        row = conn.execute(
            "SELECT request_id, kind, task_id, dispute_id, requested_by, reason, amount_minor, currency, "
            "required_approvals, status, outcome_decision FROM approval_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        votes = tuple(
            Vote(*v)
            for v in conn.execute(
                "SELECT founder, verdict, note, at FROM approval_votes WHERE request_id = ? ORDER BY id",
                (request_id,),
            )
        )
        rid, kind, tid, did, by, reason, amount, currency, required, status, outcome = (
            row
        )
        return ApprovalRequest(
            rid,
            RequestKind(kind),
            tid,
            did,
            by,
            reason,
            amount,
            currency,
            required,
            RequestStatus(status),
            outcome,
            votes,
        )

    def required_approvals(self, amount_minor: int) -> int:
        """D-019: 1 grundare upp till HUMAN_APPROVAL_THRESHOLD, annars 2. En saknad gräns betyder 2 (ER-02)."""
        threshold = self._limits.human_approval_threshold
        if threshold is None:
            return 2 if amount_minor > 0 else 1
        return 2 if amount_minor > threshold.amount_minor else 1

    # --- Internt -----------------------------------------------------------------------------

    def _enqueue(
        self,
        kind: RequestKind,
        actor: str,
        task_id: int,
        dispute_id: int | None,
        reason: str,
        amount_minor: int,
        payload: str,
        required: int | None = None,
    ) -> ApprovalRequest:
        required = required or self.required_approvals(amount_minor)
        with self._db.transaction() as tx:
            request_id = tx.execute(
                "INSERT INTO approval_requests (kind, task_id, dispute_id, requested_by, reason, amount_minor, "
                "currency, required_approvals, payload, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    kind.value,
                    task_id,
                    dispute_id,
                    actor,
                    reason,
                    amount_minor,
                    self._limits.currency,
                    required,
                    payload,
                    self._clock(),
                ),
            ).lastrowid
        self._audit.append(
            actor,
            "approval.requested",
            {
                "request_id": request_id,
                "kind": kind.value,
                "task_id": task_id,
                "dispute_id": dispute_id,
                "amount_minor": amount_minor,
                "required_approvals": required,
            },
        )
        return self.get(request_id)

    def _vote(
        self, founder: str, request_id: int, verdict: str, note: str
    ) -> ApprovalRequest:
        if founder not in self._founders:
            self._audit.append(
                founder,
                "approval.denied",
                {"request_id": request_id, "reason": "inte grundare"},
            )
            raise ApprovalError(
                f"{founder!r} är inte grundare; bara grundarna kan godkänna (D-019)"
            )
        request = self.get(request_id)
        if request is None or request.status is not RequestStatus.PENDING:
            raise ApprovalError(
                f"förfrågan {request_id} finns inte eller är redan avgjord"
            )
        if any(v.founder == founder for v in request.votes):
            raise ApprovalError(f"{founder} har redan röstat på förfrågan {request_id}")
        if mask_secrets(note) != note:
            raise ApprovalError(
                "kommentaren innehåller något som ser ut som en hemlighet"
            )
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO approval_votes (request_id, founder, verdict, note, at) VALUES (?, ?, ?, ?, ?)",
                (request_id, founder, verdict, note.strip(), self._clock()),
            )
        self._audit.append(
            founder, "approval.vote", {"request_id": request_id, "verdict": verdict}
        )
        return self.get(request_id)

    def _finish(
        self,
        request: ApprovalRequest,
        status: RequestStatus,
        outcome: int | None,
        actor: str,
    ) -> ApprovalRequest:
        with self._db.transaction() as tx:
            tx.execute(
                "UPDATE approval_requests SET status = ?, outcome_decision = ?, decided_at = ? WHERE request_id = ?",
                (status.value, outcome, self._clock(), request.request_id),
            )
        self._audit.append(
            actor,
            f"approval.{status.value}",
            {
                "request_id": request.request_id,
                "kind": request.kind.value,
                "outcome_decision": outcome,
            },
        )
        return self.get(request.request_id)

    def _payload(self, request_id: int) -> dict:
        (payload,) = self._db.connection.execute(
            "SELECT payload FROM approval_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        return json.loads(payload)

    def _pending_for_dispute(self, dispute_id: int) -> bool:
        return (
            self._db.connection.execute(
                "SELECT 1 FROM approval_requests WHERE dispute_id = ? AND status = 'pending'",
                (dispute_id,),
            ).fetchone()
            is not None
        )

    def _dispute_violations(self, request: ApprovalRequest) -> list[str]:
        dispute = self._disputes.get(request.dispute_id)
        return hard_limit_violations(
            self._limits, dispute.proposal_budget, dispute.proposal_risk_class
        )


def _draft_json(draft: DecisionDraft) -> str:
    data = asdict(draft)
    data["risk_class"] = draft.risk_class.value
    data["evidence"] = list(draft.evidence)
    return json.dumps(data, ensure_ascii=False)


def _draft_from_json(data: dict) -> DecisionDraft:
    data = dict(data)
    data["risk_class"] = RiskClass(data["risk_class"])
    data["evidence"] = tuple(data["evidence"])
    return DecisionDraft(**data)


__all__ = [
    "ApprovalError",
    "ApprovalQueue",
    "ApprovalRequest",
    "DecisionError",
    "RequestKind",
    "RequestStatus",
    "Vote",
]
