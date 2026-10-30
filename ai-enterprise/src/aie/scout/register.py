"""Scoutens möjlighetsregister (migration 37). Append-only: varje ändring är en ny version med ett skäl."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..monitoring import mask_secrets

TYPES = ("digital", "pod", "service", "other")  # pod = print-on-demand, service = tjänst på en marknadsplats
STATUSES = (
    "new",
    "researching",
    "scored",
    "proposed",
    "approved",
    "testing",
    "stopped",
    "succeeded",
)
TERMINAL = ("stopped", "succeeded")
# Vilka statusbyten scouten själv får göra. approved/testing/succeeded kommer bara från grundarna.
SCOUT_MOVES = {
    "new": {"researching", "scored", "stopped"},
    "researching": {"scored", "stopped"},
    "scored": {"researching", "scored", "proposed", "stopped"},
    "proposed": {"approved", "stopped", "scored"},
    "approved": {"testing", "stopped"},
    "testing": {"succeeded", "stopped"},
}


class RegisterError(ValueError):
    """Ändringen avvisades; inget sparades."""


@dataclass(frozen=True, slots=True)
class Entry:
    key: str
    version: int
    type: str
    niche: str
    title: str
    status: str
    data: dict
    reason: str
    actor: str
    at: str


def kind_to_type(kind: str) -> str:
    return {"service": "service", "pod": "pod"}.get(kind, "digital" if kind else "other")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ScoutRegister:
    def __init__(self, db, audit, clock: Callable[[], str] = _now) -> None:
        self._db, self._audit, self._clock = db, audit, clock

    def record(
        self,
        actor: str,
        key: str,
        type_: str,
        niche: str,
        title: str,
        status: str,
        data: dict,
        reason: str,
    ) -> Entry:
        if type_ not in TYPES or status not in STATUSES:
            raise RegisterError(f"okänd typ {type_!r} eller status {status!r}")
        if not reason.strip():
            raise RegisterError("varje ändring behöver ett skäl")
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if mask_secrets(text) != text or mask_secrets(reason) != reason:
            raise RegisterError(
                "registret får aldrig innehålla något som ser ut som en hemlighet (SR-10)"
            )
        current = self.get(key)
        if (
            current is not None
            and current.status != status
            and status not in SCOUT_MOVES.get(current.status, set())
        ):
            raise RegisterError(f"{key}: {current.status} → {status} är inte tillåtet")
        version = 1 if current is None else current.version + 1
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO scout_entries (key, version, type, niche, title, status, data, reason, actor, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    version,
                    type_,
                    niche,
                    title,
                    status,
                    text,
                    reason.strip()[:500],
                    actor,
                    self._clock(),
                ),
            )
        self._audit.append(
            actor, "scout.recorded", {"opportunity": key, "version": version, "status": status}
        )
        return self.get(key)

    def move(self, actor: str, key: str, status: str, reason: str, **extra) -> Entry:
        e = self.get(key)
        if e is None:
            raise RegisterError(f"{key} finns inte")
        return self.record(
            actor, key, e.type, e.niche, e.title, status, e.data | extra, reason
        )

    def get(self, key: str) -> Entry | None:
        row = self._db.connection.execute(
            "SELECT key, version, type, niche, title, status, data, reason, actor, at FROM scout_entries "
            "WHERE key = ? ORDER BY version DESC LIMIT 1",
            (key,),
        ).fetchone()
        return _entry(row)

    def current(self) -> list[Entry]:
        rows = self._db.connection.execute(
            "SELECT key, version, type, niche, title, status, data, reason, actor, at FROM scout_entries e "
            "WHERE version = (SELECT MAX(version) FROM scout_entries WHERE key = e.key) ORDER BY key"
        ).fetchall()
        return [_entry(r) for r in rows]

    def history(self, key: str) -> list[Entry]:
        rows = self._db.connection.execute(
            "SELECT key, version, type, niche, title, status, data, reason, actor, at FROM scout_entries "
            "WHERE key = ? ORDER BY version",
            (key,),
        ).fetchall()
        return [_entry(r) for r in rows]

    def profile(self) -> dict:
        """Scoutens prestation (§33): förslagens kvalitet och prognosprecision, aldrig intäkter direkt."""
        proposed = approved = 0
        errors = []
        for key in {e.key for e in self.current()}:
            statuses = [h.status for h in self.history(key)]
            if "proposed" in statuses:
                proposed += 1
                approved += any(
                    s in ("approved", "testing", "succeeded") for s in statuses
                )
            last = self.get(key).data
            if last.get("actual_sales_90d") is not None and last.get("est_sales_90d"):
                errors.append(
                    abs(last["actual_sales_90d"] - last["est_sales_90d"])
                    / max(1, last["est_sales_90d"])
                )
        return {
            "proposed": proposed,
            "approved": approved,
            "approval_rate": round(approved / proposed, 2) if proposed else None,
            "forecast_error": round(sum(errors) / len(errors), 2) if errors else None,
            "forecasts_measured": len(errors),
        }


def _entry(row) -> Entry | None:
    if row is None:
        return None
    return Entry(
        row[0],
        row[1],
        row[2],
        row[3],
        row[4],
        row[5],
        json.loads(row[6]),
        row[7],
        row[8],
        row[9],
    )
