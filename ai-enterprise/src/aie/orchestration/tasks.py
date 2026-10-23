"""Uppgifter (FR-07): skapas, tilldelas, följs upp och avslutas. Varje uppgift har ägare och status.

Status:
    open → assigned → in_progress → done
                 ↘        ↕
                   blocked
    Alla icke-avslutade → cancelled.  done och cancelled är slutgiltiga.

Vem får göra vad (kontrolleras av kod, SR-01):
- **Skapa:** grundare, eller agent med verktyget `task.create`.
- **Tilldela eller byta ägare:** grundare, eller agent med `task.assign`. Den nya ägaren
  måste finnas och vara i ett tillstånd som får agera. En agent kan inte tilldela sig själv.
- **Starta, blockera, återuppta, slutföra:** bara ägaren (eller en grundare).
- **Avbryta:** den som skapade uppgiften, en agent med `task.assign`, eller en grundare.

Varje ändring skrivs till `task_events` i samma transaktion. Databasen hindrar att uppgifter
raderas och att avslutade uppgifter ändras (migration 5).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ..agents import ACTING_STATES, AgentRegistry
from ..authorization import AuthorizationEngine
from ..memory import Database


class TaskStatus(str, Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


T = TaskStatus
FINAL = frozenset({T.DONE, T.CANCELLED})


class TaskError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Task:
    task_id: int
    title: str
    description: str
    created_by: str
    owner_id: str | None
    status: TaskStatus


@dataclass(frozen=True, slots=True)
class TaskEvent:
    task_id: int
    event: str
    actor: str
    owner_id: str | None
    old_status: TaskStatus | None
    new_status: TaskStatus
    note: str
    at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskBoard:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        engine: AuthorizationEngine,
        founders: frozenset[str],
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._db = db
        self._registry = registry
        self._engine = engine
        self._founders = frozenset(founders)
        self._clock = clock

    # --- Kommandon -------------------------------------------------------------------------

    def create(self, actor: str, title: str, description: str = "") -> Task:
        self._require(actor, "task.create")
        if not title.strip():
            raise TaskError("en uppgift behöver en titel")
        now = self._clock()
        with self._db.transaction() as tx:
            cursor = tx.execute(
                "INSERT INTO tasks (title, description, created_by, owner_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, NULL, ?, ?, ?)",
                (title.strip(), description, actor, T.OPEN.value, now, now),
            )
            task = Task(cursor.lastrowid, title.strip(), description, actor, None, T.OPEN)
            self._event(tx, task, "created", actor, None, "", now)
        return task

    def assign(self, actor: str, task_id: int, owner_id: str, note: str = "") -> Task:
        self._require(actor, "task.assign")
        if actor == owner_id:
            raise TaskError("en agent kan inte tilldela en uppgift till sig själv")
        owner = self._registry.get(owner_id)
        if owner is None or owner.state not in ACTING_STATES:
            raise TaskError(f"{owner_id!r} finns inte eller får inte ta uppgifter just nu")
        with self._db.transaction() as tx:
            task = self._fetch_open(tx, task_id)
            if task.status not in (T.OPEN, T.ASSIGNED, T.BLOCKED):
                raise TaskError(f"uppgiften är {task.status.value} och kan inte få ny ägare")
            event = "assigned" if task.owner_id is None else "reassigned"
            return self._update(tx, task, T.ASSIGNED, actor, event, note, owner_id=owner_id)

    def start(self, actor: str, task_id: int, note: str = "") -> Task:
        return self._owner_step(actor, task_id, {T.ASSIGNED, T.BLOCKED}, T.IN_PROGRESS, "started", note)

    def block(self, actor: str, task_id: int, note: str) -> Task:
        if not note.strip():
            raise TaskError("ange varför uppgiften är blockerad")
        return self._owner_step(actor, task_id, {T.ASSIGNED, T.IN_PROGRESS}, T.BLOCKED, "blocked", note)

    def complete(self, actor: str, task_id: int, note: str) -> Task:
        if not note.strip():
            raise TaskError("ange vad som blev gjort (§7: inget påstått slutfört utan underlag)")
        return self._owner_step(actor, task_id, {T.IN_PROGRESS}, T.DONE, "completed", note)

    def cancel(self, actor: str, task_id: int, note: str) -> Task:
        if not note.strip():
            raise TaskError("ange varför uppgiften avbryts")
        # Behörigheten kontrolleras före transaktionen: kontrollen skriver själv till audit-loggen.
        existing = self.get(task_id)
        if existing is None:
            raise TaskError(f"uppgift {task_id} finns inte")
        if not (actor in self._founders or actor == existing.created_by or self._allowed(actor, "task.assign")):
            raise TaskError(f"{actor!r} får inte avbryta uppgift {task_id}")
        with self._db.transaction() as tx:
            task = self._fetch_open(tx, task_id)
            return self._update(tx, task, T.CANCELLED, actor, "cancelled", note, owner_id=task.owner_id)

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, task_id: int) -> Task | None:
        return _row_to_task(self._db.connection.execute(_SELECT + " WHERE task_id = ?", (task_id,)).fetchone())

    def tasks(self, owner_id: str | None = None, status: TaskStatus | None = None) -> tuple[Task, ...]:
        sql, params = _SELECT + " WHERE 1 = 1", []
        if owner_id is not None:
            sql, params = sql + " AND owner_id = ?", [*params, owner_id]
        if status is not None:
            sql, params = sql + " AND status = ?", [*params, status.value]
        return tuple(_row_to_task(r) for r in self._db.connection.execute(sql + " ORDER BY task_id", params))

    def events(self, task_id: int) -> tuple[TaskEvent, ...]:
        rows = self._db.connection.execute(
            "SELECT task_id, event, actor, owner_id, old_status, new_status, note, at "
            "FROM task_events WHERE task_id = ? ORDER BY id",
            (task_id,),
        )
        return tuple(
            TaskEvent(tid, ev, actor, owner, T(old) if old else None, T(new), note, at)
            for tid, ev, actor, owner, old, new, note, at in rows
        )

    # --- Internt ---------------------------------------------------------------------------

    def _allowed(self, actor: str, tool: str) -> bool:
        return actor in self._founders or self._engine.check(actor, tool).allowed

    def _require(self, actor: str, tool: str) -> None:
        if actor not in self._founders:
            self._engine.require(actor, tool)  # PermissionDenied om inte tillåtet, och loggat

    def _owner_step(
        self, actor: str, task_id: int, allowed_from: set[TaskStatus], target: TaskStatus, event: str, note: str
    ) -> Task:
        with self._db.transaction() as tx:
            task = self._fetch_open(tx, task_id)
            if actor != task.owner_id and actor not in self._founders:
                raise TaskError(f"bara ägaren ({task.owner_id}) får {event_verb(event)} uppgift {task_id}")
            if task.status not in allowed_from:
                raise TaskError(f"uppgiften är {task.status.value}; {event_verb(event)} går inte härifrån")
            return self._update(tx, task, target, actor, event, note, owner_id=task.owner_id)

    def _fetch_open(self, tx: sqlite3.Connection, task_id: int) -> Task:
        task = _row_to_task(tx.execute(_SELECT + " WHERE task_id = ?", (task_id,)).fetchone())
        if task is None:
            raise TaskError(f"uppgift {task_id} finns inte")
        if task.status in FINAL:
            raise TaskError(f"uppgift {task_id} är {task.status.value} och kan inte ändras")
        return task

    def _update(
        self, tx: sqlite3.Connection, task: Task, target: TaskStatus, actor: str, event: str, note: str,
        owner_id: str | None,
    ) -> Task:
        now = self._clock()
        tx.execute(
            "UPDATE tasks SET status = ?, owner_id = ?, updated_at = ? WHERE task_id = ?",
            (target.value, owner_id, now, task.task_id),
        )
        updated = Task(task.task_id, task.title, task.description, task.created_by, owner_id, target)
        self._event(tx, updated, event, actor, task.status, note, now)
        return updated

    @staticmethod
    def _event(
        tx: sqlite3.Connection, task: Task, event: str, actor: str, old: TaskStatus | None, note: str, at: str
    ) -> None:
        tx.execute(
            "INSERT INTO task_events (task_id, event, actor, owner_id, old_status, new_status, note, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task.task_id, event, actor, task.owner_id, old.value if old else None, task.status.value, note, at),
        )


_SELECT = "SELECT task_id, title, description, created_by, owner_id, status FROM tasks"


def _row_to_task(row) -> Task | None:
    return None if row is None else Task(*row[:5], TaskStatus(row[5]))


def event_verb(event: str) -> str:
    return {"started": "starta", "blocked": "blockera", "completed": "slutföra"}.get(event, event)
