"""Agent Runtime (ARCHITECTURE.md §2): agentregister och livscykel. Förberedelse för Fas 2."""
from .hierarchy import (
    LEVEL_CEO,
    LEVEL_CONTROL,
    LEVEL_FOUNDERS,
    LEVEL_HEAD,
    LEVEL_WORKER,
    OrgChart,
    reporting_line_error,
)
from .lifecycle import ACTING_STATES, TRANSITIONS, AgentState, IllegalTransition, check_transition
from .registry import Agent, AgentRegistry, RegistryError, StateChange

__all__ = [
    "LEVEL_CEO",
    "LEVEL_CONTROL",
    "LEVEL_FOUNDERS",
    "LEVEL_HEAD",
    "LEVEL_WORKER",
    "OrgChart",
    "reporting_line_error",
    "ACTING_STATES",
    "TRANSITIONS",
    "Agent",
    "AgentRegistry",
    "AgentState",
    "IllegalTransition",
    "RegistryError",
    "StateChange",
    "check_transition",
]
