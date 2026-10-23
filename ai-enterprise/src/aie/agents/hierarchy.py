"""Hierarkin i konstitutionen §8 (FR-09, D-020): nivåer, rapportvägar och departementschefer.

Nivå 0  grundarna (Yorgo, Robin). Ingen roll; de står utanför registret.
Nivå 1  CEO
Nivå 2  kontrollfunktioner: CFO, CRO, Compliance, Audit
Nivå 3  departementschefer
Nivå 4  arbetsagenter
Nivå 5  tillfälliga arbetsgrupper (byggs senare, FR-14)

Rapportvägar som koden kräver:
- Nivå 1 och 2 rapporterar direkt till grundarna. Kontrollfunktionerna får inte lyda under CEO,
  annars kan CEO styra sin egen granskning (§8 nivå 2, §18).
- En departementschef (3) rapporterar till CEO (1).
- En arbetsagent (4) rapporterar till en chef på nivå 2 eller 3 *i samma departement*.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..authorization.permissions import Permissions
    from .registry import Agent, AgentRegistry

LEVEL_FOUNDERS = 0
LEVEL_CEO, LEVEL_CONTROL, LEVEL_HEAD, LEVEL_WORKER = 1, 2, 3, 4
ROLE_LEVELS = (LEVEL_CEO, LEVEL_CONTROL, LEVEL_HEAD, LEVEL_WORKER)
LEVEL_NAMES = {
    LEVEL_FOUNDERS: "grundare",
    LEVEL_CEO: "CEO",
    LEVEL_CONTROL: "kontrollfunktion",
    LEVEL_HEAD: "departementschef",
    LEVEL_WORKER: "arbetsagent",
}


def reporting_line_error(
    level: int, department: str, manager_level: int | None, manager_department: str | None
) -> str | None:
    """Returnerar ett felmeddelande om rapportvägen bryter mot §8, annars None.

    `manager_level` är None när agenten rapporterar direkt till grundarna.
    """
    name = LEVEL_NAMES.get(level, f"nivå {level}")
    if level in (LEVEL_CEO, LEVEL_CONTROL):
        if manager_level is not None:
            return f"en {name} rapporterar direkt till grundarna, inte till en annan agent (§8)"
        return None
    if level == LEVEL_HEAD:
        if manager_level != LEVEL_CEO:
            return "en departementschef rapporterar till CEO (§8 nivå 3)"
        return None
    if level == LEVEL_WORKER:
        if manager_level not in (LEVEL_CONTROL, LEVEL_HEAD):
            return "en arbetsagent måste ha en chef på nivå 2 eller 3 (§8 nivå 4)"
        if manager_department != department:
            return f"chefen måste finnas i samma departement ({department}), inte i {manager_department}"
        return None
    return f"okänd nivå {level}"


class OrgChart:
    """Läser hierarkin ur registret. Ändrar ingenting."""

    def __init__(self, registry: AgentRegistry, permissions: Permissions) -> None:
        self._registry = registry
        self._permissions = permissions

    def level(self, agent_id: str) -> int:
        agent = self._require(agent_id)
        return self._permissions.roles[agent.role].level

    def chain_of_command(self, agent_id: str) -> tuple[str, ...]:
        """Från agenten upp till den som rapporterar till grundarna, t.ex. ('res-1', 'lead-1', 'ceo-1')."""
        chain, current, seen = [], self._require(agent_id), set()
        while current is not None:
            if current.agent_id in seen:  # kan inte hända med reglerna ovan, men skydda ändå
                raise ValueError(f"cykel i befälskedjan vid {current.agent_id}")
            seen.add(current.agent_id)
            chain.append(current.agent_id)
            current = self._registry.get(current.manager_id) if current.manager_id else None
        return tuple(chain)

    def subordinates(self, agent_id: str) -> tuple[str, ...]:
        return tuple(a.agent_id for a in self._registry.agents() if a.manager_id == agent_id)

    def department_heads(self, department: str) -> tuple[str, ...]:
        return tuple(a.agent_id for a in self._active_at(LEVEL_HEAD) if a.department == department)

    def control_functions(self) -> tuple[str, ...]:
        return tuple(a.agent_id for a in self._active_at(LEVEL_CONTROL))

    def is_above(self, superior: str, subordinate: str) -> bool:
        """Står `superior` i `subordinate`s befälskedja (och är inte agenten själv)?"""
        return superior != subordinate and superior in self.chain_of_command(subordinate)

    def _active_at(self, level: int) -> Iterator[Agent]:
        from .lifecycle import AgentState

        for agent in self._registry.agents():
            if agent.state is not AgentState.RETIRED and self._permissions.roles[agent.role].level == level:
                yield agent

    def _require(self, agent_id: str) -> Agent:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise ValueError(f"agenten {agent_id!r} finns inte")
        return agent
