"""Utlösarna: vad som ska ge en notis, läst ur revisionsloggen och godkännandekön (FR-33).

| Typ       | Utlöses av                                                                       |
|-----------|----------------------------------------------------------------------------------|
| kill      | `kill.engaged`                                                                   |
| protected | `mode.protected_entered`                                                         |
| limit     | `stoploss.tripped` (en riskgräns är nådd)                                        |
| blocked   | `tool.denied`, `budget.blocked` (en handling blockerad av kontrollkedjan)        |
| waiting   | en förfrågan i godkännandekön som har väntat mer än 1 timme                      |
| quota     | `simulation.paused_quota`, `dev.quota_exhausted`, `llm.unavailable` (kvoten slut) |

Vad som redan är aviserat står i revisionsloggen (`notify.sent`: sista raden som lästes och vilka förfrågningar
som aviserats), så ingenting aviseras två gånger och inget nytt tillstånd behöver sparas någon annanstans.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

ACTIONS = {
    "kill.engaged": "kill", "mode.protected_entered": "protected", "stoploss.tripped": "limit",
    "tool.denied": "blocked", "budget.blocked": "blocked",
    "simulation.paused_quota": "quota", "dev.quota_exhausted": "quota", "llm.unavailable": "quota",
}
# Det enda som skickas till ntfy: fasta texter utan belopp, namn eller ID:n (D-091).
GENERIC = {
    "kill": "The kill switch is on. Open Command Center.",
    "protected": "Protected mode is on. Open Command Center.",
    "limit": "A risk limit was reached. Open Command Center.",
    "blocked": "An action was blocked by the control chain.",
    "waiting": "A decision has waited more than one hour for a founder.",
    "quota": "The free model quota is used up. Agents are waiting.",
}
PRIORITY = ("kill", "protected", "limit", "waiting", "quota", "blocked")
WAIT = timedelta(hours=1)
FIRST_RUN_WINDOW = timedelta(hours=24)
REPEAT = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class Alert:
    kind: str
    count: int
    detail: str  # för e-post: får innehålla ID:n och belopp i SIM

    @property
    def generic(self) -> str:
        return GENERIC[self.kind]


def _state(db) -> tuple[int, set[int], dict[str, str]]:
    """(sista lästa seq, aviserade förfrågningar, senaste tid per typ) ur `notify.sent` i revisionsloggen."""
    seq, pending, last = 0, set(), {}
    for timestamp, details in db.connection.execute(
            "SELECT timestamp, details FROM audit_log WHERE action = 'notify.sent' ORDER BY seq"):
        d = json.loads(details)
        seq = max(seq, int(d.get("up_to_seq") or 0))
        pending |= set(d.get("pending") or [])
        for kind in d.get("kinds") or []:
            last[kind] = timestamp
    return seq, pending, last


def collect(db, now: datetime | None = None) -> tuple[list[Alert], dict]:
    """Returnerar (larm att skicka, det som ska sparas i `notify.sent` när de är skickade)."""
    now = now or datetime.now(UTC)
    since, notified, last = _state(db)
    conn = db.connection
    top = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM audit_log").fetchone()[0]
    floor = (now - FIRST_RUN_WINDOW).isoformat() if since == 0 else ""
    counts: dict[str, int] = {}
    details: dict[str, list[str]] = {}
    for timestamp, action, raw in conn.execute(
            "SELECT timestamp, action, details FROM audit_log WHERE seq > ? AND timestamp >= ? ORDER BY seq",
            (since, floor)):
        kind = ACTIONS.get(action)
        if kind is None:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        d = json.loads(raw)
        what = d.get("tool") or d.get("reason") or d.get("limit_name") or ""
        details.setdefault(kind, []).append(f"{timestamp[:16]} {action} {str(what)[:120]}".strip())
    waiting = [(rid, by, amount, cur, created) for rid, by, amount, cur, created in conn.execute(
        "SELECT request_id, requested_by, amount_minor, currency, created_at FROM approval_requests "
        "WHERE status = 'pending' ORDER BY request_id")
        if rid not in notified and _older(created, now, WAIT)]
    if waiting:
        counts["waiting"] = len(waiting)
        details["waiting"] = [f"request #{rid} from {by}: {amount / 100:.2f} {cur}, waiting since {created[:16]}"
                              for rid, by, amount, cur, created in waiting]
    alerts = []
    for kind in PRIORITY:
        if kind not in counts:
            continue
        if kind in last and not _older(last[kind], now, REPEAT):
            continue  # högst en notis per typ var 15:e minut
        alerts.append(Alert(kind, counts[kind], "\n".join(details[kind][:20])))
    record = {"up_to_seq": top, "kinds": [a.kind for a in alerts],
              "pending": [w[0] for w in waiting] if any(a.kind == "waiting" for a in alerts) else []}
    return alerts, record


def _older(timestamp: str, now: datetime, delta: timedelta) -> bool:
    try:
        at = datetime.fromisoformat(timestamp)
    except ValueError:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return now - at >= delta
