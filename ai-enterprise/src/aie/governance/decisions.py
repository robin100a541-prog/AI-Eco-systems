"""Beslutsloggen (Fas 3, FR-10, konstitutionen §20 steg 7 och §51).

Varje beslut sparas i tabellen `decisions` (migration 9) med de åtta fälten i §20 steg 7:
vald åtgärd, motivering, underlag, budget, riskklass, förväntat resultat, villkor för
avbrytande och krav på uppföljning. Varje beslut hör till den uppgift som orsakade det,
så det finns alltid spårbarhet från uppgift till beslut (§51). Tabellen är append-only;
ett beslut som behöver ändras ersätts av ett nytt beslut som pekar på det gamla.

Vem får besluta (§20 steg 7–8, kontrolleras av kod):
- **Agenter** behöver verktyget `decision.record` i sitt mandat (Authorization Engine; ett
  nej revideras). De får bara besluta om uppgifter de äger eller har skapat.
- **Beloppsgräns:** ett beslut vars budget är högre än `HUMAN_APPROVAL_THRESHOLD` får
  ingen agent och ingen ensam grundare fatta (D-019). Det kastar `NeedsApproval`, och
  beslutet går i stället till grundarnas godkännandekö.
- **Grundare** får besluta upp till gränsen.

Fritext med något som ser ut som en hemlighet avvisas, eftersom loggen aldrig kan rensas (SR-10).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from ..audit import AuditLog
from ..authorization import AuthorizationEngine
from ..config import RiskLimits
from ..memory import Database
from ..monitoring import mask_secrets
from ..orchestration import Task, TaskBoard, TaskEvent, TaskStatus

TOOL = "decision.record"


class RiskClass(str, Enum):
    """Riskklass enligt §24. Bestäms innan beslutet godkänns."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionError(ValueError):
    """Beslutet är ofullständigt eller otillåtet och sparades inte."""


class NeedsApproval(PermissionError):
    """Beslutet ligger över det beslutsfattaren själv får besluta och måste godkännas (D-019)."""

    def __init__(
        self, actor: str, task_id: int, amount_minor: int, currency: str, reason: str
    ) -> None:
        self.actor, self.task_id = actor, task_id
        self.amount_minor, self.currency, self.reason = amount_minor, currency, reason
        super().__init__(
            f"{actor} får inte fatta beslutet om uppgift {task_id} ensam: {reason}"
        )


@dataclass(frozen=True, slots=True)
class Decision:
    decision_id: int
    task_id: int
    decided_by: str
    chosen_action: str
    reasoning: str
    evidence: tuple[str, ...]
    budget_minor: int
    currency: str
    risk_class: RiskClass
    expected_result: str
    stop_conditions: str
    follow_up: str
    supersedes: int | None
    decided_at: str


@dataclass(frozen=True, slots=True)
class DecisionDraft:
    """Ett beslut som ännu inte är fattat: de åtta fälten i §20 steg 7."""

    chosen_action: str
    reasoning: str
    evidence: tuple[str, ...]
    budget_minor: int
    risk_class: RiskClass
    expected_result: str
    stop_conditions: str
    follow_up: str
    supersedes: int | None = None


@dataclass(frozen=True, slots=True)
class Trace:
    """Hela kedjan från uppgift till beslut (§51)."""

    task: Task
    task_events: tuple[TaskEvent, ...]
    decisions: tuple[Decision, ...]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DecisionLog:
    def __init__(
        self,
        db: Database,
        board: TaskBoard,
        engine: AuthorizationEngine,
        limits: RiskLimits,
        founders: frozenset[str],
        audit: AuditLog,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._db = db
        self._board = board
        self._engine = engine
        self._limits = limits
        self._founders = frozenset(founders)
        self._audit = audit
        self._clock = clock

    # --- Kommandon -------------------------------------------------------------------------

    def record(self, actor: str, task_id: int, draft: DecisionDraft) -> Decision:
        """Fattar beslutet om `actor` har befogenhet. Annars `PermissionDenied`, `NeedsApproval` eller `DecisionError`."""
        if actor not in self._founders:
            self._engine.require(actor, TOOL)  # nej revideras av motorn
        task = self.check_task(task_id)
        if actor not in self._founders and actor not in (
            task.owner_id,
            task.created_by,
        ):
            raise DecisionError(
                f"{actor} äger inte uppgift {task_id} och har inte skapat den"
            )
        self.validate(draft, task_id)
        self.check_authority(actor, task_id, draft.budget_minor)
        return self._insert(actor, task_id, draft)

    def check_task(self, task_id: int) -> Task:
        """Uppgiften måste finnas och inte vara avbruten; ett beslut hör alltid till en uppgift (§51)."""
        task = self._board.get(task_id)
        if task is None:
            raise DecisionError(f"uppgift {task_id} finns inte; ett beslut måste höra till en uppgift (§51)")
        if task.status is TaskStatus.CANCELLED:
            raise DecisionError(f"uppgift {task_id} är avbruten; inga nya beslut om den")
        return task

    def record_approved(
        self, approvers: Sequence[str], task_id: int, draft: DecisionDraft
    ) -> Decision:
        """Sparar ett beslut som grundarna har godkänt i godkännandekön (används av escalation)."""
        if not approvers or not set(approvers) <= self._founders:
            raise DecisionError("bara grundare kan godkänna ett eskalerat beslut")
        if self._board.get(task_id) is None:
            raise DecisionError(f"uppgift {task_id} finns inte")
        self.validate(draft, task_id)
        return self._insert("+".join(sorted(set(approvers))), task_id, draft)

    def check_authority(self, actor: str, task_id: int, budget_minor: int) -> None:
        """D-019: över HUMAN_APPROVAL_THRESHOLD får varken en agent eller en ensam grundare besluta."""
        threshold = self._limits.human_approval_threshold
        currency = self._limits.currency
        if threshold is None:  # ER-02: en saknad gräns betyder blockera
            if budget_minor > 0:
                raise NeedsApproval(
                    actor,
                    task_id,
                    budget_minor,
                    currency,
                    "HUMAN_APPROVAL_THRESHOLD saknas (ER-02)",
                )
            return
        if budget_minor > threshold.amount_minor:
            raise NeedsApproval(
                actor,
                task_id,
                budget_minor,
                currency,
                f"budgeten {budget_minor} är över HUMAN_APPROVAL_THRESHOLD {threshold.amount_minor}; båda grundarna krävs (D-019)",
            )

    def validate(self, draft: DecisionDraft, task_id: int) -> None:
        """Alla åtta fälten i §20 steg 7 måste finnas. Samlar alla fel."""
        errors = []
        texts = {
            "chosen_action": draft.chosen_action,
            "reasoning": draft.reasoning,
            "expected_result": draft.expected_result,
            "stop_conditions": draft.stop_conditions,
            "follow_up": draft.follow_up,
        }
        for name, value in texts.items():
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{name} saknas (§20 steg 7)")
        if not draft.evidence or not all(
            isinstance(e, str) and e.strip() for e in draft.evidence
        ):
            errors.append("evidence måste innehålla minst ett underlag (§20 steg 7)")
        if (
            not isinstance(draft.budget_minor, int)
            or isinstance(draft.budget_minor, bool)
            or draft.budget_minor < 0
        ):
            errors.append(
                "budget_minor måste vara ett heltal >= 0 i minsta enhet (D-006)"
            )
        if not isinstance(draft.risk_class, RiskClass):
            errors.append(
                "risk_class måste vara low, medium, high eller critical (§24)"
            )
        for text in (*texts.values(), *draft.evidence):
            if isinstance(text, str) and mask_secrets(text) != text:
                errors.append(
                    "texten innehåller något som ser ut som en hemlighet (SR-10)"
                )
                break
        if draft.supersedes is not None:
            old = self.get(draft.supersedes)
            if old is None or old.task_id != task_id:
                errors.append(
                    f"supersedes={draft.supersedes} är inget beslut om uppgift {task_id}"
                )
        if errors:
            raise DecisionError("; ".join(errors))

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, decision_id: int) -> Decision | None:
        row = self._db.connection.execute(
            _SELECT + " WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        return _row(row)

    def for_task(self, task_id: int) -> tuple[Decision, ...]:
        rows = self._db.connection.execute(
            _SELECT + " WHERE task_id = ? ORDER BY decision_id", (task_id,)
        )
        return tuple(_row(r) for r in rows)

    def trace(self, decision_id: int) -> Trace:
        """Från ett beslut tillbaka till uppgiften, dess historik och alla beslut om den (§51)."""
        decision = self.get(decision_id)
        if decision is None:
            raise DecisionError(f"beslut {decision_id} finns inte")
        task = self._board.get(decision.task_id)
        return Trace(
            task, self._board.events(task.task_id), self.for_task(task.task_id)
        )

    # --- Internt ---------------------------------------------------------------------------

    def _insert(self, decided_by: str, task_id: int, draft: DecisionDraft) -> Decision:
        now = self._clock()
        evidence = tuple(e.strip() for e in draft.evidence)
        with self._db.transaction() as tx:
            cursor = tx.execute(
                "INSERT INTO decisions (task_id, decided_by, chosen_action, reasoning, evidence, budget_minor, "
                "currency, risk_class, expected_result, stop_conditions, follow_up, supersedes, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    decided_by,
                    draft.chosen_action.strip(),
                    draft.reasoning.strip(),
                    json.dumps(list(evidence), ensure_ascii=False),
                    draft.budget_minor,
                    self._limits.currency,
                    draft.risk_class.value,
                    draft.expected_result.strip(),
                    draft.stop_conditions.strip(),
                    draft.follow_up.strip(),
                    draft.supersedes,
                    now,
                ),
            )
            decision_id = cursor.lastrowid
        self._audit.append(
            decided_by,
            "decision.recorded",
            {
                "decision_id": decision_id,
                "task_id": task_id,
                "budget_minor": draft.budget_minor,
                "currency": self._limits.currency,
                "risk_class": draft.risk_class.value,
                "supersedes": draft.supersedes,
            },
        )
        return self.get(decision_id)


_SELECT = (
    "SELECT decision_id, task_id, decided_by, chosen_action, reasoning, evidence, budget_minor, currency, "
    "risk_class, expected_result, stop_conditions, follow_up, supersedes, decided_at FROM decisions"
)


def _row(row) -> Decision | None:
    if row is None:
        return None
    (
        did,
        tid,
        by,
        action,
        reasoning,
        evidence,
        budget,
        currency,
        risk,
        expected,
        stop,
        follow,
        sup,
        at,
    ) = row
    return Decision(
        did,
        tid,
        by,
        action,
        reasoning,
        tuple(json.loads(evidence)),
        budget,
        currency,
        RiskClass(risk),
        expected,
        stop,
        follow,
        sup,
        at,
    )
