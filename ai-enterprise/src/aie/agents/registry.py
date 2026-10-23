"""Agentregister (FR-05). Varje agent har ID, roll, departement, chef och livscykelstatus.

Förberedelse inför Fas 2: registret ligger i minnet. Det sparas i databasen först när
Fas 1 är klar, så att migrationsnumret inte krockar med 1.6–1.7.
Gränssnittet (`register`, `get`, `transition`, `history`) ska vara detsamma då.

Regler som upprätthålls här:
- Ett ID registreras bara en gång, och rollen måste finnas i `permissions.toml`.
- Chefen måste redan finnas och inte vara avvecklad. En agent kan inte vara sin egen chef.
- En agent kan aldrig ändra sin egen status (SR-03); `changed_by` måste vara någon annan.
- Varje statusändring sparas i historiken med vem, varför och tid. Historiken raderas aldrig (SR-14).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .lifecycle import AgentState, check_transition

if TYPE_CHECKING:  # bara för typning; authorization importerar agents, inte tvärtom
    from ..authorization.permissions import Permissions

_AGENT_ID = re.compile(r"[a-z][a-z0-9_-]{1,63}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Agent:
    agent_id: str
    role: str
    department: str  # hämtas från rollen, kan inte sättas separat
    manager_id: str | None  # None = rapporterar direkt till grundarna
    state: AgentState = AgentState.PROPOSED


@dataclass(frozen=True, slots=True)
class StateChange:
    agent_id: str
    old: AgentState | None  # None = registrering
    new: AgentState
    changed_by: str
    reason: str
    at: str


class AgentRegistry:
    def __init__(self, permissions: Permissions, clock: Callable[[], str] = _utc_now) -> None:
        self._permissions = permissions
        self._clock = clock
        self._agents: dict[str, Agent] = {}
        self._history: list[StateChange] = []

    def register(self, agent_id: str, role: str, manager_id: str | None, registered_by: str, reason: str) -> Agent:
        if not _AGENT_ID.fullmatch(agent_id):
            raise RegistryError(f"ogiltigt agent-ID {agent_id!r} (gemener, siffror, - och _, 2–64 tecken)")
        if agent_id in self._agents:
            raise RegistryError(f"agenten {agent_id!r} finns redan")
        mandate = self._permissions.roles.get(role)
        if mandate is None:
            raise RegistryError(f"rollen {role!r} finns inte i permissions.toml")
        if manager_id is not None:
            if manager_id == agent_id:
                raise RegistryError("en agent kan inte vara sin egen chef")
            manager = self._agents.get(manager_id)
            if manager is None or manager.state is AgentState.RETIRED:
                raise RegistryError(f"chefen {manager_id!r} finns inte eller är avvecklad")
        _require_reason(reason)
        agent = Agent(agent_id, role, mandate.department, manager_id)
        self._agents[agent_id] = agent
        self._history.append(StateChange(agent_id, None, agent.state, registered_by, reason, self._clock()))
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    def transition(self, agent_id: str, target: AgentState, changed_by: str, reason: str) -> Agent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise RegistryError(f"agenten {agent_id!r} finns inte")
        if changed_by == agent_id:
            raise RegistryError("en agent kan inte ändra sin egen status (SR-03)")
        _require_reason(reason)
        check_transition(agent.state, target)
        updated = replace(agent, state=target)
        self._agents[agent_id] = updated
        self._history.append(StateChange(agent_id, agent.state, target, changed_by, reason, self._clock()))
        return updated

    def history(self, agent_id: str | None = None) -> tuple[StateChange, ...]:
        return tuple(c for c in self._history if agent_id is None or c.agent_id == agent_id)


def _require_reason(reason: str) -> None:
    if not reason or not reason.strip():
        raise RegistryError("en motivering krävs (§33: avveckling ska bygga på dokumenterade skäl)")
