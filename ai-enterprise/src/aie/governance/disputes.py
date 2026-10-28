"""Oenighet mellan agenter (Fas 3, FR-12, konstitutionen §21).

En tvist gäller en uppgift och ett förslag (åtgärd, budget, riskklass). Systemet registrerar
exakt vilka påståenden agenterna är oense om, vilka underlag som stöder varje ståndpunkt och
om konflikten gäller mål, data, risk eller metod (`goal`, `data`, `risk`, `method`).
Ståndpunkter och händelser är append-only (migration 10).

Flöde:
1. `open()`: minst två ståndpunkter från olika agenter. Ingen falsk konsensus (§21).
2. `request_analysis()`: begär kompletterande analys, till exempel när ett påstående saknar underlag.
3. `resolve()`: en agent med `dispute.resolve` som inte själv är part (CEO), eller en grundare.
4. `escalate()`: kvarstår konflikten går den till rätt nivå, CEO eller grundarna.

Hårda gränser (§21: "Chefer får inte åsidosätta hårda säkerhets- eller budgetgränser genom att
rösta igenom ett riskfyllt beslut"): ett förslag som bryter mot `MAX_SINGLE_TRANSACTION`,
`MAX_DEPARTMENT_BUDGET` eller `MAX_SINGLE_EXPERIMENT_LOSS`, saknar en av gränserna (ER-02) eller
har riskklass `critical` kan aldrig godtas genom `resolve()`, oavsett röster och oavsett vem som
avgör. Tvisten eskaleras då till grundarna. Gränserna ändras bara via `risk_limits.toml`, vilket
kräver en grundare (D-019, D-049). Ett förslag över `HUMAN_APPROVAL_THRESHOLD` kräver grundarna (D-019).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from ..agents import ACTING_STATES, AgentRegistry
from ..audit import AuditLog
from ..authorization import AuthorizationEngine
from ..config import RiskLimits
from ..memory import Database
from ..monitoring import mask_secrets
from ..orchestration import TaskBoard
from .decisions import NeedsApproval, RiskClass

TOOL = "dispute.resolve"
HARD_LIMITS = (
    "max_single_transaction",
    "max_department_budget",
    "max_single_experiment_loss",
)


class ConflictType(str, Enum):
    """Vad konflikten gäller (§21)."""

    GOAL = "goal"
    DATA = "data"
    RISK = "risk"
    METHOD = "method"


class DisputeStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Level(str, Enum):
    CEO = "ceo"
    FOUNDERS = "founders"


class DisputeError(ValueError):
    pass


class HardLimitViolation(PermissionError):
    """Förslaget bryter mot en hård gräns och kan inte godtas, oavsett röster (§21)."""

    def __init__(self, dispute_id: int, violations: Sequence[str]) -> None:
        self.dispute_id, self.violations = dispute_id, tuple(violations)
        super().__init__(
            f"tvist {dispute_id}: förslaget bryter mot hårda gränser: "
            + "; ".join(violations)
        )


@dataclass(frozen=True, slots=True)
class Position:
    agent_id: str
    claim: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Dispute:
    dispute_id: int
    task_id: int
    conflict_type: ConflictType
    proposal: str
    proposal_budget: int
    proposal_risk_class: RiskClass
    opened_by: str
    status: DisputeStatus
    escalated_to: Level | None
    positions: tuple[Position, ...]

    @property
    def parties(self) -> frozenset[str]:
        return frozenset(p.agent_id for p in self.positions)

    @property
    def unsupported_claims(self) -> tuple[Position, ...]:
        """Ståndpunkter utan underlag; de behöver kompletterande analys (§21)."""
        return tuple(p for p in self.positions if not p.evidence)


@dataclass(frozen=True, slots=True)
class DisputeEvent:
    event: str
    actor: str
    note: str
    at: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def hard_limit_violations(
    limits: RiskLimits, budget_minor: int, risk_class: RiskClass
) -> list[str]:
    """Alla hårda gränser som förslaget bryter mot. Tom lista = inom gränserna."""
    violations = []
    if risk_class is RiskClass.CRITICAL:
        violations.append("riskklass critical: pausa, minska eller eskalera (§21)")
    for name in HARD_LIMITS:
        limit = getattr(limits, name)
        if limit is None:
            if budget_minor > 0:
                violations.append(
                    f"{name.upper()} saknas; en saknad gräns betyder blockera (ER-02)"
                )
        elif budget_minor > limit.amount_minor:
            violations.append(
                f"budgeten {budget_minor} är över {name.upper()} {limit.amount_minor}"
            )
    return violations


class DisputeBoard:
    def __init__(
        self,
        db: Database,
        board: TaskBoard,
        registry: AgentRegistry,
        engine: AuthorizationEngine,
        limits: RiskLimits,
        founders: frozenset[str],
        audit: AuditLog,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._db = db
        self._board = board
        self._registry = registry
        self._engine = engine
        self._limits = limits
        self._founders = frozenset(founders)
        self._audit = audit
        self._clock = clock

    # --- Kommandon -------------------------------------------------------------------------

    def open(
        self,
        actor: str,
        task_id: int,
        conflict_type: ConflictType,
        proposal: str,
        proposal_budget: int,
        proposal_risk_class: RiskClass,
        positions: Sequence[Position],
    ) -> Dispute:
        """Registrerar en tvist. Kräver minst två ståndpunkter från olika, aktiva agenter."""
        errors = []
        if self._board.get(task_id) is None:
            errors.append(f"uppgift {task_id} finns inte")
        if not isinstance(conflict_type, ConflictType):
            errors.append(
                "conflict_type måste vara goal, data, risk eller method (§21)"
            )
        if not isinstance(proposal_risk_class, RiskClass):
            errors.append(
                "proposal_risk_class måste vara low, medium, high eller critical (§24)"
            )
        if not proposal.strip():
            errors.append("förslaget saknas")
        if (
            not isinstance(proposal_budget, int)
            or isinstance(proposal_budget, bool)
            or proposal_budget < 0
        ):
            errors.append("proposal_budget måste vara ett heltal >= 0")
        agents = [p.agent_id for p in positions]
        if len(set(agents)) < 2:
            errors.append("en tvist kräver ståndpunkter från minst två olika agenter")
        for p in positions:
            agent = self._registry.get(p.agent_id)
            if agent is None or agent.state not in ACTING_STATES:
                errors.append(f"{p.agent_id!r} finns inte eller får inte agera")
            if not p.claim.strip():
                errors.append(f"{p.agent_id}: påståendet saknas")
        if (
            actor not in self._founders
            and actor not in agents
            and not self._can_resolve(actor)
        ):
            errors.append(f"{actor} är varken part, grundare eller har {TOOL}")
        texts = [
            proposal,
            *(p.claim for p in positions),
            *(e for p in positions for e in p.evidence),
        ]
        if any(mask_secrets(t) != t for t in texts):
            errors.append("texten innehåller något som ser ut som en hemlighet (SR-10)")
        if errors:
            raise DisputeError("; ".join(errors))

        now = self._clock()
        with self._db.transaction() as tx:
            dispute_id = tx.execute(
                "INSERT INTO disputes (task_id, conflict_type, proposal, proposal_budget, proposal_risk_class, "
                "opened_by, status, opened_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
                (
                    task_id,
                    conflict_type.value,
                    proposal.strip(),
                    proposal_budget,
                    proposal_risk_class.value,
                    actor,
                    now,
                ),
            ).lastrowid
            for p in positions:
                tx.execute(
                    "INSERT INTO dispute_positions (dispute_id, agent_id, claim, evidence, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        dispute_id,
                        p.agent_id,
                        p.claim.strip(),
                        json.dumps([e.strip() for e in p.evidence]),
                        now,
                    ),
                )
            self._event(
                tx, dispute_id, "opened", actor, f"{len(positions)} ståndpunkter", now
            )
        self._audit.append(
            actor,
            "dispute.opened",
            {
                "dispute_id": dispute_id,
                "task_id": task_id,
                "conflict_type": conflict_type.value,
                "parties": sorted(set(agents)),
                "proposal_budget": proposal_budget,
                "proposal_risk_class": proposal_risk_class.value,
            },
        )
        return self.get(dispute_id)

    def request_analysis(
        self, actor: str, dispute_id: int, from_agent: str, question: str
    ) -> None:
        """Begär kompletterande analys (§21). Händelsen sparas och revideras."""
        dispute = self._open_dispute(dispute_id)
        if (
            actor not in self._founders
            and actor not in dispute.parties
            and not self._can_resolve(actor)
        ):
            raise DisputeError(f"{actor} får inte begära analys i tvist {dispute_id}")
        if not question.strip() or mask_secrets(question) != question:
            raise DisputeError("frågan saknas eller innehåller en hemlighet")
        with self._db.transaction() as tx:
            self._event(
                tx,
                dispute_id,
                "analysis_requested",
                actor,
                f"{from_agent}: {question.strip()}",
                self._clock(),
            )
        self._audit.append(
            actor,
            "dispute.analysis_requested",
            {"dispute_id": dispute_id, "from_agent": from_agent},
        )

    def resolve(
        self,
        actor: str,
        dispute_id: int,
        accept_proposal: bool,
        resolution: str,
        votes: Mapping[str, bool] | None = None,
    ) -> Dispute:
        """Avgör tvisten. Röster sparas men kan aldrig häva hårda gränser eller D-019."""
        dispute = self.get(dispute_id)
        if dispute is None or dispute.status is DisputeStatus.RESOLVED:
            raise DisputeError(f"tvist {dispute_id} finns inte eller är redan avgjord")
        if actor in dispute.parties:
            raise DisputeError(
                f"{actor} är part i tvist {dispute_id} och kan inte avgöra den"
            )
        if actor not in self._founders:
            self._engine.require(actor, TOOL)  # nej revideras av motorn
            if dispute.escalated_to is Level.FOUNDERS:
                raise DisputeError(f"tvist {dispute_id} är eskalerad till grundarna")
        if not resolution.strip() or mask_secrets(resolution) != resolution:
            raise DisputeError("motiveringen saknas eller innehåller en hemlighet")
        note = resolution.strip()
        if votes:
            yes = sum(1 for v in votes.values() if v)
            note += f" (röster: {yes} ja, {len(votes) - yes} nej; röster påverkar inte gränserna)"

        if accept_proposal:
            violations = hard_limit_violations(
                self._limits, dispute.proposal_budget, dispute.proposal_risk_class
            )
            if violations:
                self.escalate(
                    actor,
                    dispute_id,
                    "hårda gränser: " + "; ".join(violations),
                    level=Level.FOUNDERS,
                )
                self._audit.append(
                    actor,
                    "dispute.hard_limit_blocked",
                    {"dispute_id": dispute_id, "violations": violations},
                )
                raise HardLimitViolation(dispute_id, violations)
            threshold = self._limits.human_approval_threshold
            if actor not in self._founders and (
                threshold is None or dispute.proposal_budget > threshold.amount_minor
            ):
                self.escalate(
                    actor,
                    dispute_id,
                    "över HUMAN_APPROVAL_THRESHOLD (D-019)",
                    level=Level.FOUNDERS,
                )
                raise NeedsApproval(
                    actor,
                    dispute.task_id,
                    dispute.proposal_budget,
                    self._limits.currency,
                    "förslaget är över HUMAN_APPROVAL_THRESHOLD; en grundare krävs (D-019, D-049)",
                )

        with self._db.transaction() as tx:
            tx.execute(
                "UPDATE disputes SET status = 'resolved' WHERE dispute_id = ?",
                (dispute_id,),
            )
            verdict = "förslaget godtas" if accept_proposal else "förslaget avslås"
            self._event(
                tx, dispute_id, "resolved", actor, f"{verdict}: {note}", self._clock()
            )
        self._audit.append(
            actor,
            "dispute.resolved",
            {
                "dispute_id": dispute_id,
                "accepted": accept_proposal,
                "votes": len(votes or {}),
            },
        )
        return self.get(dispute_id)

    def resolve_approved(
        self, approvers: Sequence[str], dispute_id: int, accept_proposal: bool, resolution: str
    ) -> Dispute:
        """Avgör en tvist som grundarna har godkänt i godkännandekön (D-019).

        Hårda gränser gäller även här: ett förslag som bryter mot dem kan aldrig godtas,
        bara avslås. Gränserna ändras bara i risk_limits.toml.
        """
        if not approvers or not set(approvers) <= self._founders:
            raise DisputeError("bara grundare kan avgöra via godkännandekön")
        dispute = self.get(dispute_id)
        if dispute is None or dispute.status is DisputeStatus.RESOLVED:
            raise DisputeError(f"tvist {dispute_id} finns inte eller är redan avgjord")
        if accept_proposal:
            violations = hard_limit_violations(self._limits, dispute.proposal_budget, dispute.proposal_risk_class)
            if violations:
                raise HardLimitViolation(dispute_id, violations)
        actor = "+".join(sorted(set(approvers)))
        with self._db.transaction() as tx:
            tx.execute("UPDATE disputes SET status = 'resolved' WHERE dispute_id = ?", (dispute_id,))
            verdict = "förslaget godtas" if accept_proposal else "förslaget avslås"
            self._event(tx, dispute_id, "resolved", actor, f"{verdict} av grundarna: {resolution.strip()}", self._clock())
        self._audit.append(actor, "dispute.resolved", {"dispute_id": dispute_id, "accepted": accept_proposal, "votes": 0})
        return self.get(dispute_id)

    def escalate(
        self, actor: str, dispute_id: int, reason: str, level: Level | None = None
    ) -> Level:
        """Skickar en kvarstående konflikt till rätt nivå (§21). Returnerar nivån."""
        dispute = self._open_dispute(dispute_id, allow_escalated=True)
        if (
            actor not in self._founders
            and actor not in dispute.parties
            and not self._can_resolve(actor)
        ):
            raise DisputeError(f"{actor} får inte eskalera tvist {dispute_id}")
        target = level or self.right_level(dispute)
        if dispute.escalated_to is Level.FOUNDERS and target is Level.CEO:
            target = Level.FOUNDERS  # aldrig nedåt
        with self._db.transaction() as tx:
            if dispute.escalated_to is not target:  # redan på rätt nivå: bara händelsen sparas
                tx.execute(
                    "UPDATE disputes SET status = 'escalated', escalated_to = ? WHERE dispute_id = ?",
                    (target.value, dispute_id),
                )
            self._event(
                tx,
                dispute_id,
                "escalated",
                actor,
                f"till {target.value}: {reason}",
                self._clock(),
            )
        self._audit.append(
            actor, "dispute.escalated", {"dispute_id": dispute_id, "to": target.value}
        )
        return target

    def right_level(self, dispute: Dispute) -> Level:
        """Grundarna om förslaget bryter mot gränser, är över D-019-gränsen, är kritiskt eller CEO är part.
        Annars CEO, om det finns en aktiv CEO som inte är part."""
        threshold = self._limits.human_approval_threshold
        if (
            hard_limit_violations(
                self._limits, dispute.proposal_budget, dispute.proposal_risk_class
            )
            or threshold is None
            or dispute.proposal_budget > threshold.amount_minor
        ):
            return Level.FOUNDERS
        for agent in self._registry.agents():
            if (
                agent.role == "ceo"
                and agent.state in ACTING_STATES
                and agent.agent_id not in dispute.parties
            ):
                return Level.CEO
        return Level.FOUNDERS

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, dispute_id: int) -> Dispute | None:
        conn = self._db.connection
        row = conn.execute(
            "SELECT dispute_id, task_id, conflict_type, proposal, proposal_budget, proposal_risk_class, "
            "opened_by, status, escalated_to FROM disputes WHERE dispute_id = ?",
            (dispute_id,),
        ).fetchone()
        if row is None:
            return None
        positions = tuple(
            Position(agent, claim, tuple(json.loads(evidence)))
            for agent, claim, evidence in conn.execute(
                "SELECT agent_id, claim, evidence FROM dispute_positions WHERE dispute_id = ? ORDER BY position_id",
                (dispute_id,),
            )
        )
        did, tid, ctype, proposal, budget, risk, opened_by, status, level = row
        return Dispute(
            did,
            tid,
            ConflictType(ctype),
            proposal,
            budget,
            RiskClass(risk),
            opened_by,
            DisputeStatus(status),
            Level(level) if level else None,
            positions,
        )

    def for_task(self, task_id: int) -> tuple[Dispute, ...]:
        ids = self._db.connection.execute(
            "SELECT dispute_id FROM disputes WHERE task_id = ? ORDER BY dispute_id",
            (task_id,),
        )
        return tuple(self.get(i) for (i,) in ids)

    def events(self, dispute_id: int) -> tuple[DisputeEvent, ...]:
        rows = self._db.connection.execute(
            "SELECT event, actor, note, at FROM dispute_events WHERE dispute_id = ? ORDER BY id",
            (dispute_id,),
        )
        return tuple(DisputeEvent(*r) for r in rows)

    # --- Internt ---------------------------------------------------------------------------

    def _can_resolve(self, actor: str) -> bool:
        return self._engine.check(actor, TOOL).allowed

    def _open_dispute(self, dispute_id: int, allow_escalated: bool = False) -> Dispute:
        dispute = self.get(dispute_id)
        if dispute is None:
            raise DisputeError(f"tvist {dispute_id} finns inte")
        if dispute.status is DisputeStatus.RESOLVED or (
            dispute.status is DisputeStatus.ESCALATED and not allow_escalated
        ):
            raise DisputeError(f"tvist {dispute_id} är {dispute.status.value}")
        return dispute

    @staticmethod
    def _event(tx, dispute_id: int, event: str, actor: str, note: str, at: str) -> None:
        tx.execute(
            "INSERT INTO dispute_events (dispute_id, event, actor, note, at) VALUES (?, ?, ?, ?, ?)",
            (dispute_id, event, actor, note, at),
        )
