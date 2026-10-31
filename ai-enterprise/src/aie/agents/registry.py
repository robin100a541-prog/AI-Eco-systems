"""Agentregister (FR-05). Varje agent har ID, roll, departement, chef och livscykelstatus.

Registret sparas i databasen (migration 4) och överlever därför omstart (FR-03).
Databasen själv skyddar det viktigaste. Agenter kan inte raderas, roll och chef kan inte
ändras, och historiken är append-only. Koden här lägger till reglerna:
- Ett ID registreras bara en gång, och rollen måste finnas i `permissions.toml`.
- Chefen måste redan finnas och inte vara avvecklad. En agent kan inte vara sin egen chef.
- Rapportvägen måste följa hierarkin i §8 (se `hierarchy.py`). Kontrollfunktionerna lyder till exempel inte under CEO.
- En agent kan aldrig ändra sin egen status (SR-03); `changed_by` måste vara någon annan.
- Varje statusändring kräver en motivering och sparas i historiken med vem och när (SR-14).
- Statusändring och historikrad skrivs i samma transaktion: antingen båda eller ingen.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .hierarchy import reporting_line_error
from .lifecycle import AgentState, check_transition

if TYPE_CHECKING:  # bara för typning; authorization importerar agents, inte tvärtom
    from ..authorization.permissions import Permissions
    from ..memory import Database

_AGENT_ID = re.compile(r"[a-z][a-z0-9_-]{1,63}")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_SANCTIONS = frozenset({AgentState.SUSPENDED, AgentState.RETIRED})  # SR-17: kräver dokumenterade kriterier
_SERVING = frozenset({AgentState.ACTIVE, AgentState.PROBATION, AgentState.SUSPENDED})


class RegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Agent:
    agent_id: str
    role: str
    department: str  # hämtas från rollen, kan inte sättas separat
    manager_id: str | None  # None = rapporterar direkt till grundarna
    state: AgentState = AgentState.PROPOSED

    def __repr__(self) -> str:
        return f"Agent({self.agent_id!r}, {self.role!r}, {self.department!r}, {self.manager_id!r}, {self.state!r})"


@dataclass(frozen=True, slots=True)
class StateChange:
    agent_id: str
    old: AgentState | None  # None = registrering
    new: AgentState
    changed_by: str
    reason: str
    at: str


class AgentRegistry:
    def __init__(self, permissions: Permissions, db: Database, clock: Callable[[], str] = _utc_now) -> None:
        self._permissions = permissions
        self._db = db
        self._clock = clock
        self._guard = None

    def set_guard(self, guard) -> None:
        """SR-17 (D-040): avstängning och avveckling av en verksam agent kräver då ett beslutat ärende.

        `guard.transition_block_reason(agent_id, old, new, changed_by) -> str | None`; None = tillåtet.
        """
        self._guard = guard

    def register(self, agent_id: str, role: str, manager_id: str | None, registered_by: str, reason: str) -> Agent:
        if not _AGENT_ID.fullmatch(agent_id):
            raise RegistryError(f"ogiltigt agent-ID {agent_id!r} (gemener, siffror, - och _, 2–64 tecken)")
        mandate = self._permissions.roles.get(role)
        if mandate is None:
            raise RegistryError(f"rollen {role!r} finns inte i permissions.toml")
        if manager_id == agent_id:
            raise RegistryError("en agent kan inte vara sin egen chef")
        # manager_id != agent_id
        _require_reason(reason)

        now = self._clock()
        agent = Agent(agent_id, role, mandate.department, manager_id)
        with self._db.transaction() as tx:
            if self._fetch(tx, agent_id) is not None:
                raise RegistryError(f"agenten {agent_id!r} finns redan")
            manager_level = manager_department = None
            if manager_id is not None:
                manager = self._fetch(tx, manager_id)
                if manager is None or manager.state is AgentState.RETIRED:
                    raise RegistryError(f"chefen {manager_id!r} finns inte eller är avvecklad")
                manager_level = self._permissions.roles[manager.role].level
                manager_department = manager.department
            problem = reporting_line_error(mandate.level, mandate.department, manager_level, manager_department)
            if problem:
                raise RegistryError(f"{agent_id} ({role}): {problem}")
            tx.execute(
                "INSERT INTO agents (agent_id, role, department, manager_id, state, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, role, agent.department, manager_id, agent.state.value, now),
            )
            self._record(tx, StateChange(agent_id, None, agent.state, registered_by, reason, now))
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return self._fetch(self._db.connection, agent_id)

    def agents(self) -> Iterator[Agent]:
        rows = self._db.connection.execute(
            "SELECT agent_id, role, department, manager_id, state FROM agents ORDER BY agent_id"
        )
        for agent_id, role, department, manager_id, state in rows:
            yield Agent(agent_id, role, department, manager_id, AgentState(state))

    def transition(self, agent_id: str, target: AgentState, changed_by: str, reason: str) -> Agent:
        if changed_by == agent_id:
            raise RegistryError("en agent kan inte ändra sin egen status (SR-03)")
        _require_reason(reason)
        with self._db.transaction() as tx:  # BEGIN IMMEDIATE: läsning och skrivning hänger ihop
            agent = self._fetch(tx, agent_id)
            if agent is None:
                raise RegistryError(f"agenten {agent_id!r} finns inte")
            check_transition(agent.state, target)
            if self._guard is not None and target in _SANCTIONS and agent.state in _SERVING:
                blocked = self._guard.transition_block_reason(agent_id, agent.state, target, changed_by)
                if blocked:
                    raise RegistryError(blocked)
            tx.execute("UPDATE agents SET state = ? WHERE agent_id = ?", (target.value, agent_id))
            self._record(tx, StateChange(agent_id, agent.state, target, changed_by, reason, self._clock()))
        return Agent(agent.agent_id, agent.role, agent.department, agent.manager_id, target)

    def history(self, agent_id: str | None = None) -> tuple[StateChange, ...]:
        sql = "SELECT agent_id, old_state, new_state, changed_by, reason, at FROM agent_state_changes"
        params: tuple[str, ...] = ()
        if agent_id is not None:
            sql, params = sql + " WHERE agent_id = ?", (agent_id,)
        rows = self._db.connection.execute(sql + " ORDER BY id", params)
        return tuple(
            StateChange(a, AgentState(old) if old else None, AgentState(new), by, reason, at)
            for a, old, new, by, reason, at in rows
        )

    @staticmethod
    def _fetch(conn, agent_id: str) -> Agent | None:
        row = conn.execute(
            "SELECT agent_id, role, department, manager_id, state FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return None if row is None else Agent(*row[:4], AgentState(row[4]))

    @staticmethod
    def _record(conn, change: StateChange) -> None:
        conn.execute(
            "INSERT INTO agent_state_changes (agent_id, old_state, new_state, changed_by, reason, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (change.agent_id, change.old.value if change.old else None, change.new.value,
             change.changed_by, change.reason, change.at),
        )


def _require_reason(reason: str) -> None:
    if not reason or not reason.strip():
        raise RegistryError("en motivering krävs (§33: avveckling ska bygga på dokumenterade skäl)")
