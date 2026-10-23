"""Authorization Engine (ARCHITECTURE.md §2): rollmandat och default deny. Förberedelse för Fas 2."""
from .engine import AuthorizationEngine, Decision, PermissionDenied
from .permissions import (
    DEPARTMENTS,
    LEVEL_CEO,
    LEVEL_CONTROL,
    LEVEL_HEAD,
    LEVEL_WORKER,
    PROTECTED_PREFIX,
    Mandate,
    Permissions,
    load_permissions,
)

__all__ = [
    "DEPARTMENTS",
    "LEVEL_CEO",
    "LEVEL_CONTROL",
    "LEVEL_HEAD",
    "LEVEL_WORKER",
    "PROTECTED_PREFIX",
    "AuthorizationEngine",
    "Decision",
    "Mandate",
    "PermissionDenied",
    "Permissions",
    "load_permissions",
]
