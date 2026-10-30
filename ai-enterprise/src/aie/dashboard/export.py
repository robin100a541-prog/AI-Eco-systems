"""`aie export-status`: skriver `docs/dashboard/status.json` för instrumentpanelen (Fas 8).

Bara data som får vara offentliga (DR-13) går ut, och bara genom en vitlista av fält:
- agenterna: ID, förnamn, roll, departement, livscykelstatus och en **generisk** aktivitet
  (`ACTIVITY`, härledd ur senaste åtgärdens typ, aldrig fritext, prompter eller modellsvar),
- rollplan och historisk aktivitet; faktisk livefas läggs bara på av arbetscykelns observatör,
- antal öppna tvister, som inte i sig bevisar ett pågående möte,
- poängtavlan: kapital, reserv och resultat, med SIM och riktig valuta var för sig.
Varje textvärde kontrolleras mot `mask_secrets`; ett värde som ser ut som en hemlighet stoppar exporten.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ..monitoring import mask_secrets

NAMES = ("Astrid", "Bertil", "Cecilia", "David", "Elsa", "Filip", "Greta", "Hugo", "Ingrid", "Johan", "Karin",
         "Lars", "Maja", "Nils", "Olivia", "Per", "Rut", "Sven", "Tove", "Ulf", "Vera", "Wilhelm", "Ylva", "Åke")
ACTIVITY = {  # åtgärdstyp i revisionsloggen -> vad pratbubblan säger
    "llm.call": "tänker", "decision.recorded": "fattar beslut", "dispute.opened": "i tvist",
    "dispute.escalated": "eskalerar", "task.created": "planerar", "task.assigned": "delar ut arbete",
    "forecast.made": "gör en prognos", "proposal.submitted": "lämnar förslag", "sim.action": "arbetar",
    "tool.denied": "nekad av spärrarna", "ledger.recorded": "bokför",
}
ROLE_PLANS = {
    "researcher": "Undersök marknaden och lämna belagda förslag",
    "research_lead": "Granska förslag och prioritera nästa experiment",
    "cfo": "Granska ekonomi när en bedömning behövs",
    "cro": "Granska risker när en bedömning behövs",
    "ceo": "Avgör eskalerade frågor och prioritera arbetet",
    "compliance": "Kontrollera regler när ett ärende behöver granskas",
    "auditor": "Granska rapporter och revisionskedjan",
}
AGENT_FIELDS = ("id", "name", "role", "department", "state", "activity", "work")
WORK_FIELDS = ("phase", "current", "next", "last", "updated_at")


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


def _activity(system, agent_id: str) -> str:
    row = system.db.connection.execute(
        "SELECT action FROM audit_log WHERE actor = ? ORDER BY seq DESC LIMIT 1", (agent_id,)).fetchone()
    return ACTIVITY.get(row[0], "arbetar") if row else "väntar"


def _score(system, currency: str) -> dict:
    from ..budget.capital import capital_position
    from ..ledger import compute_result

    entries = system.ledger.entries(currency)
    if not entries:
        return {"currency": currency, "capital_minor": None, "reserve_minor": None, "result_minor": None}
    pos = capital_position(entries, system.budget._limits)
    return {"currency": currency, "capital_minor": pos.liquid_minor, "reserve_minor": pos.reserve_minor,
            "result_minor": compute_result(entries, currency).net_minor}


def build_status(system, real_system=None, now: str | None = None) -> dict:
    agents = list(system.registry.agents())
    names = ensure_names(system.db, [a.agent_id for a in agents])
    timestamp = now or datetime.now(UTC).isoformat(timespec="seconds")
    pending = system.db.connection.execute(
        "SELECT COUNT(*) FROM disputes WHERE status != 'resolved'").fetchone()[0] if _has(system.db, "disputes") else 0
    status = {
        "generated_at": timestamp,
        "classification": "public",
        "departments": sorted({a.department for a in agents}),
        "agents": [{"id": a.agent_id, "name": names[a.agent_id], "role": a.role, "department": a.department,
                    "state": a.state.value, "activity": _activity(system, a.agent_id),
                    "work": {"phase": "idle", "current": "Ingen arbetscykel körs just nu",
                             "next": ROLE_PLANS.get(a.role, "Invänta tilldelad uppgift"),
                             "last": _activity(system, a.agent_id), "updated_at": timestamp}} for a in agents],
        "meeting": False,  # ett öppet ärende bevisar inte att ett möte pågår
        "meetings": [],
        "pending_discussions": pending,
        "execution": {"state": "offline", "heartbeat_at": None, "lease_seconds": 10},
        "kill_switch": system.kill.state().engaged,
        "protected_mode": system.protected.state().protected,
        "scoreboard": {"sim": _score(system, "SIM"),
                       "real": _score(real_system, real_system.currency) if real_system is not None else None},
    }
    check_public(status)
    return status


def _has(db, table: str) -> bool:
    return db.connection.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None


def check_public(value, path: str = "") -> None:
    """Stoppar exporten om ett textvärde ser ut som en hemlighet, eller om ett agentfält inte är vitlistat."""
    if isinstance(value, dict):
        if path.endswith("agents[]") and set(value) - set(AGENT_FIELDS):
            raise ValueError(f"fält utanför vitlistan i {path}: {sorted(set(value) - set(AGENT_FIELDS))}")
        if path.endswith(".work") and set(value) - set(WORK_FIELDS):
            raise ValueError(f"fält utanför vitlistan i {path}")
        for k, v in value.items():
            check_public(v, f"{path}.{k}")
    elif isinstance(value, list):
        for v in value:
            check_public(v, f"{path}[]")
    elif isinstance(value, str) and mask_secrets(value) != value:
        raise ValueError(f"{path} ser ut att innehålla en hemlighet; exporten stoppas (SR-10, DR-13)")


def write_status(status: dict, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    check_public(status)
    # Readers see either the previous complete snapshot or the next one, never half a JSON file.
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out.parent,
                                         prefix=f".{out.name}.", suffix=".tmp", delete=False) as stream:
            name = stream.name
            stream.write(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
        os.replace(name, out)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)
    return out


def export(config_dir: Path, out: Path, pilot_root: Path | None = Path("data-pilot")) -> int:
    """CLI: SIM ur repots databas, riktig valuta ur pilotens databas om den finns."""
    from .. import runtime
    from ..simulation.market import SimClock
    from ..simulation.run import stored_run
    from ..system import build_system

    config = runtime._load(config_dir, console=False)
    with runtime._open(config) as db:
        run = stored_run(db)
        system = build_system(config, db, config_dir, clock=SimClock(run["start_date"]) if run else None)
        real = None
        if pilot_root is not None and (Path(pilot_root) / "config").is_dir():
            pconfig = runtime._load(Path(pilot_root) / "config", console=False)
            with runtime._open(pconfig) as pdb:
                real = build_system(pconfig, pdb, Path(pilot_root) / "config")
                status = build_status(system, real)
        else:
            status = build_status(system)
    print(f"Skrev {write_status(status, out)} ({len(status['agents'])} agenter, bara offentliga data)")
    return 0
