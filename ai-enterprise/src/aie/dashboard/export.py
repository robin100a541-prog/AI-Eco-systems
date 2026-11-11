"""Det som går ut ur systemet till Command Center: fasta agentnamn, vitlistan och kontrollen mot hemligheter.

Fram till 2026-11-10 skrev den här modulen också `docs/dashboard/status.json` för Ekobyn. Den vägen är borttagen:
Command Center läser snapshoten (`snapshot.py`), som byggs med samma vitlista och samma kontroll (DR-13, SR-10).

- `AGENT_FIELDS`: de enda fält som får finnas på en agent i snapshoten. Ett nytt fält måste läggas till här
  uttryckligen; annars stoppas snapshoten. Prompter, modellsvar och fritext från modellen finns aldrig med.
- `check_public`: stoppar allt där ett textvärde ser ut som en hemlighet (`mask_secrets`).
- `ensure_names`: varje agent får ett förnamn som aldrig ändras.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..monitoring import mask_secrets

NAMES = ("Astrid", "Bertil", "Cecilia", "David", "Elsa", "Filip", "Greta", "Hugo", "Ingrid", "Johan", "Karin",
         "Lars", "Maja", "Nils", "Olivia", "Per", "Rut", "Sven", "Tove", "Ulf", "Vera", "Wilhelm", "Ylva", "Åke")
AGENT_FIELDS = ("id", "name", "role", "department", "level", "description", "lifecycle", "paused", "status", "manager",
                "task", "progress", "model", "last_run", "runs", "actions_done", "actions_failed", "success_rate",
                "tools", "recent_runs")


def ensure_names(db, agent_ids) -> dict[str, str]:
    rows = dict(db.connection.execute("SELECT agent_id, first_name FROM agent_names").fetchall())
    used = set(rows.values())
    for agent_id in sorted(agent_ids):
        if agent_id in rows:
            continue
        name = next((n for n in NAMES if n not in used), f"Agent {len(rows) + 1}")
        with db.transaction() as tx:
            tx.execute("INSERT INTO agent_names (agent_id, first_name, at) VALUES (?, ?, ?)",
                       (agent_id, name, datetime.now(UTC).isoformat(timespec="seconds")))
        rows[agent_id] = name
        used.add(name)
    return rows


def scout_counts(db) -> dict | None:
    """Scoutens pipeline: antal möjligheter per status (bara siffror, inga källor eller texter)."""
    if not _has(db, "scout_entries"):
        return None
    rows = db.connection.execute(
        "SELECT status, COUNT(*) FROM scout_entries e WHERE version = "
        "(SELECT MAX(version) FROM scout_entries WHERE key = e.key) GROUP BY status").fetchall()
    return {status: n for status, n in rows}


def _has(db, table: str) -> bool:
    return db.connection.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None


def check_public(value, path: str = "") -> None:
    """Stoppar snapshoten om ett textvärde ser ut som en hemlighet, eller om ett agentfält inte är vitlistat."""
    if isinstance(value, dict):
        if path.endswith(("agents[]", "agents.items[]")) and set(value) - set(AGENT_FIELDS):
            raise ValueError(f"fält utanför vitlistan i {path}: {sorted(set(value) - set(AGENT_FIELDS))}")
        for k, v in value.items():
            check_public(v, f"{path}.{k}")
    elif isinstance(value, list):
        for v in value:
            check_public(v, f"{path}[]")
    elif isinstance(value, str) and mask_secrets(value) != value:
        raise ValueError(f"{path} ser ut att innehålla en hemlighet; snapshoten stoppas (SR-10, DR-13)")
