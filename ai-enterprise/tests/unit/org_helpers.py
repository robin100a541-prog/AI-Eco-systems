"""Testhjälp: registrera agenter med en giltig rapportväg enligt §8 (D-020).

Många tester handlar om behörigheter eller uppgifter, inte om hierarkin. De använder
`register_in_line`, som skapar de chefer som behövs (en CEO och en departementschef,
alla ACTIVE) innan agenten själv registreras.
"""
from aie.agents import LEVEL_CEO, LEVEL_CONTROL, LEVEL_HEAD, AgentState

ACTIVE_PATH = (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE)


def _role_at(permissions, level, department=None):
    for name, mandate in permissions.roles.items():
        if mandate.level == level and (department is None or mandate.department == department):
            return name
    return None


def _ensure_active(registry, agent_id, role, manager, by):
    if registry.get(agent_id) is None:
        registry.register(agent_id, role, manager, by, "chef som testet behöver")
        for state in ACTIVE_PATH:
            registry.transition(agent_id, state, by, "chef som testet behöver")
    return agent_id


def manager_for(registry, permissions, role, by="yorgo"):
    """En giltig chef för `role`, skapad vid behov. None för nivå 1 och 2 (rapporterar till grundarna)."""
    mandate = permissions.roles[role]
    if mandate.level <= LEVEL_CONTROL:
        return None
    ceo_role = _role_at(permissions, LEVEL_CEO)
    ceo = _ensure_active(registry, "ceo-auto", ceo_role, None, by) if ceo_role else None
    if mandate.level == LEVEL_HEAD:
        return ceo
    head_role = _role_at(permissions, LEVEL_HEAD, mandate.department)
    if head_role:
        return _ensure_active(registry, f"{mandate.department}-head-auto", head_role, ceo, by)
    control_role = _role_at(permissions, LEVEL_CONTROL, mandate.department)
    return _ensure_active(registry, f"{mandate.department}-control-auto", control_role, None, by)


def register_in_line(registry, permissions, agent_id, role, by="yorgo", reason="test"):
    return registry.register(agent_id, role, manager_for(registry, permissions, role, by), by, reason)
