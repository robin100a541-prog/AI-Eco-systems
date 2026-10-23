"""Authorization Engine (ARCHITECTURE.md §2): rollmandat och default deny. Förberedelse för Fas 2."""
from .engine import AuthorizationEngine, Decision, PermissionDenied
from .permissions import DEPARTMENTS, Mandate, Permissions, load_permissions

__all__ = [
    "DEPARTMENTS",
    "AuthorizationEngine",
    "Decision",
    "Mandate",
    "PermissionDenied",
    "Permissions",
    "load_permissions",
]
