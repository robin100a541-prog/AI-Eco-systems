"""Kommandot `python -m aie approvals` (Fas 3, FR-13, D-019): grundarnas godkännandekö.

    python -m aie approvals list
    python -m aie approvals approve 3 --as robin --note "OK enligt kalkylen"
    python -m aie approvals reject 3 --as yorgo --note "För hög risk"

`--as` måste vara en av `founders` i `config/system.toml` (D-021). Varje röst, godkännande,
avslag och nekat försök revideras av godkännandekön. Kod 0 = lyckades, kod 1 = fel som är
utskrivet och loggat.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .. import runtime
from ..agents import AgentRegistry
from ..audit import AuditLog
from ..authorization import AuthorizationEngine, load_permissions
from ..authorization.stops import ControlStops
from ..config import Config, ConfigError
from ..memory import Database
from ..monitoring import get_logger
from ..orchestration import TaskBoard
from .decisions import DecisionError, DecisionLog
from .disputes import DisputeBoard, DisputeError, HardLimitViolation
from .escalation import ApprovalError, ApprovalQueue, ApprovalRequest

log = get_logger("approvals")


@dataclass(frozen=True, slots=True)
class Governance:
    """Hela kedjan som godkännandekön behöver, byggd från konfigurationen."""

    registry: AgentRegistry
    engine: AuthorizationEngine
    board: TaskBoard
    decisions: DecisionLog
    disputes: DisputeBoard
    queue: ApprovalQueue
    audit: AuditLog


def build(config: Config, db: Database, config_dir: Path) -> Governance:
    founders = frozenset(config.system.founders)
    permissions = load_permissions(config_dir)
    audit = AuditLog(db)
    registry = AgentRegistry(permissions, db)
    stops = ControlStops(db, registry, permissions, audit, founders)
    engine = AuthorizationEngine(
        permissions, registry, config.system.environment, audit, stops=stops
    )
    board = TaskBoard(db, registry, engine, founders=founders)
    decisions = DecisionLog(db, board, engine, config.risk, founders, audit)
    disputes = DisputeBoard(db, board, registry, engine, config.risk, founders, audit)
    queue = ApprovalQueue(
        db, decisions, disputes, registry, config.risk, founders, audit
    )
    return Governance(registry, engine, board, decisions, disputes, queue, audit)


def approvals(
    config_dir: Path,
    action: str,
    request_id: int | None = None,
    founder: str | None = None,
    note: str = "",
) -> int:
    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            try:
                gov = build(config, db, config_dir)
            except (ConfigError, ApprovalError) as exc:
                raise runtime.StartupError(f"FEL: {exc}") from exc
            if action == "list":
                return _list(gov.queue.pending(), config.system.founders)
            try:
                if action == "approve":
                    result = gov.queue.approve(founder, request_id, note)
                else:
                    result = gov.queue.reject(founder, request_id, note)
            except (
                ApprovalError,
                HardLimitViolation,
                DecisionError,
                DisputeError,
            ) as exc:
                log.error(
                    "approvals %s %s av %s nekades: %s",
                    action,
                    request_id,
                    founder,
                    exc,
                )
                print(f"FEL: {exc}", file=sys.stderr)
                return 1
            print(_describe(result))
            return 0
    except runtime.StartupError as exc:
        return runtime._fail(exc)


def _list(pending: tuple[ApprovalRequest, ...], founders: tuple[str, ...]) -> int:
    if not pending:
        print("Inga förfrågningar väntar på grundarna.")
        return 0
    print(f"{len(pending)} förfrågningar väntar (grundare: {', '.join(founders)}):")
    for r in pending:
        print(_describe(r))
    return 0


def _describe(r: ApprovalRequest) -> str:
    target = f"tvist {r.dispute_id}" if r.dispute_id else f"uppgift {r.task_id}"
    votes = ", ".join(f"{v.founder}: {v.verdict}" for v in r.votes) or "inga röster"
    outcome = f", beslut {r.outcome_decision}" if r.outcome_decision else ""
    return (
        f"#{r.request_id} [{r.status.value}] {r.kind.value} om {target}: {r.amount_minor} {r.currency}, "
        f"kräver {r.required_approvals} grundare ({votes}){outcome}. Från {r.requested_by}: {r.reason}"
    )
