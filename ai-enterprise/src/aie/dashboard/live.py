"""Best-effort public telemetry. No model calls, prompts, task titles or business commands.

Only the owning work thread reads SQLite. A heartbeat thread rewrites a cached,
whitelisted snapshot. If the process dies, the browser expires its ten-second lease.
"""
from __future__ import annotations

import copy
import logging
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .export import build_status, write_status

log = logging.getLogger(__name__)
PHASES = {
    "thinking": "Bearbetar underlaget i modellen",
    "checking": "Kontrollerar föreslagna åtgärder",
    "fetching": "Läser en offentlig marknadskälla",
    "done": "Klar med detta arbetssteg",
    "blocked": "Arbetssteget kunde inte genomföras",
    "queued": "Inväntar sin tur i arbetscykeln",
    "idle": "Ingen uppgift körs just nu",
}


def now():
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class LiveStatus:
    def __init__(self, system, out: Path | None, mode: str):
        self.system, self.out, self.mode = system, Path(out) if out is not None else None, mode
        self.session = uuid4().hex
        self.work = {}
        self.meetings = []
        self.state = "running"
        self.day = None
        self.started_at = now()
        self._snapshot = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._warned = False
        self._writer_lock = None

    def __enter__(self):
        if self.out is not None:
            try:
                import fcntl

                self.out.parent.mkdir(parents=True, exist_ok=True)
                self._writer_lock = (self.out.parent / f".{self.out.name}.live.lock").open("a")
                fcntl.flock(self._writer_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (ImportError, OSError):
                if self._writer_lock is not None:
                    self._writer_lock.close()
                    self._writer_lock = None
                self._warn()
                self.out = None  # a competing writer keeps ownership; company work still proceeds
                return self
            self.publish()
            self._thread = threading.Thread(target=self._heartbeat, name="dashboard-heartbeat", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self.state = "failed" if exc_type else ("paused" if self.state == "paused" else "finished")
        self.meetings = []
        for agent_id in tuple(self.work):
            previous = self.work[agent_id]
            self.work[agent_id] = {**previous, "phase": "idle", "current": "Arbetscykeln är avslutad",
                                   "updated_at": now()}
        self.publish()
        if self._writer_lock is not None:
            self._writer_lock.close()
        return False

    def _warn(self):
        if not self._warned:
            log.warning("Dashboard-status kunde inte skrivas; arbetet fortsätter utan livevisning")
            self._warned = True

    def publish(self):
        if self.out is None:
            return
        try:
            snapshot = build_status(self.system)
            snapshot["execution"] = {"state": self.state, "session_id": self.session, "mode": self.mode,
                                     "heartbeat_at": now(), "lease_seconds": 10, "day": self.day,
                                     "started_at": self.started_at}
            snapshot["meetings"] = copy.deepcopy(self.meetings)
            snapshot["meeting"] = bool(self.meetings)
            for agent in snapshot["agents"]:
                if agent["id"] in self.work:
                    agent["work"].update(self.work[agent["id"]])
                if self.state == "running" and agent["work"]["phase"] == "idle":
                    agent["work"]["current"] = "Ingen uppgift i detta arbetssteg"
            with self._lock:
                self._snapshot = snapshot
                write_status(snapshot, self.out)
        except Exception:
            self._warn()  # instrumentation must never approve, block or retry business work

    def _heartbeat(self):
        while not self._stop.wait(2):
            try:
                with self._lock:
                    if self._snapshot is not None:
                        self._snapshot["execution"]["heartbeat_at"] = now()
                        write_status(self._snapshot, self.out)
            except Exception:
                self._warn()

    def agent(self, agent_id: str, phase: str):
        if phase not in PHASES:
            raise ValueError("unknown public phase")
        previous = self.work.get(agent_id, {})
        self.work[agent_id] = {"phase": phase, "current": PHASES[phase], "updated_at": now(),
                               "last": PHASES[phase] if phase in ("done", "blocked") else previous.get("last", "–")}
        self.publish()

    def queue(self, day: int, agent_ids):
        self.day = day
        for agent_id in agent_ids:
            self.work[agent_id] = {"phase": "queued", "current": PHASES["queued"], "updated_at": now(),
                                   "last": self.work.get(agent_id, {}).get("last", "–")}
        self.publish()

    @contextmanager
    def meeting(self, participant_ids):
        participants = sorted(set(participant_ids))
        self.meetings = [{"kind": "assessment", "participants": participants}]
        self.publish()
        try:
            yield
        finally:
            self.meetings = []
            self.publish()

    def gateway(self, gateway):
        return ObservedGateway(gateway, self)

    def reader(self, reader):
        return ObservedReader(reader, self)


class ObservedGateway:
    """Delegates the exact same request once, through all existing authorization/quota gates."""
    def __init__(self, gateway, observer):
        self.wrapped, self.observer = gateway, observer

    def calls_left(self):
        return self.wrapped.calls_left()

    def complete(self, agent_id, request):
        self.observer.agent(agent_id, "thinking")
        try:
            response = self.wrapped.complete(agent_id, request)
        except BaseException:
            self.observer.agent(agent_id, "blocked")
            raise
        self.observer.agent(agent_id, "checking")
        return response


class ObservedReader:
    def __init__(self, reader, observer):
        self.wrapped, self.observer = reader, observer

    def fetch(self, agent_id, url):
        self.observer.agent(agent_id, "fetching")
        try:
            result = self.wrapped.fetch(agent_id, url)
        except BaseException:
            self.observer.agent(agent_id, "blocked")
            raise
        self.observer.agent(agent_id, "done")
        return result
