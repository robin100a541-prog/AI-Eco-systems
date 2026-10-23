"""Agent Runtime (ARCHITECTURE.md §2): agentregister och livscykel. Förberedelse för Fas 2."""
from .lifecycle import ACTING_STATES, TRANSITIONS, AgentState, IllegalTransition, check_transition
from .registry import Agent, AgentRegistry, RegistryError, StateChange

__all__ = [
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
