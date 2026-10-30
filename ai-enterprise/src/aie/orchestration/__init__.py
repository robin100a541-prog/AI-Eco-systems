"""Orchestrator (ARCHITECTURE.md §2): uppgifter och agenter som utför dem. Hierarki och eskalering kommer i Fas 3."""
from .legal import LegalDesk, LegalError, LegalHold
from .tasks import FINAL, Task, TaskBoard, TaskError, TaskEvent, TaskStatus
from .worker import AgentWorker, WorkResult

__all__ = ["LegalDesk", "LegalError", "LegalHold", "FINAL", "AgentWorker", "Task", "TaskBoard", "TaskError", "TaskEvent", "TaskStatus", "WorkResult"]
