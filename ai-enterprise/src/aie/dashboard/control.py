"""`py -m aie control ingest`: utför grundarnas knapptryck från Command Center (Del 4, D-089).

Knapparna ändrar aldrig något direkt. `functions/api/action.js` lägger ett beslut i KV-kön (`queue:<tid>:<id>`),
och den här modulen:

1. läser kön och tar bort varje post när den är behandlad,
2. validerar posten (typ, fält, grundare, mejl, ålder, och att samma id inte redan är behandlat),
3. anropar kärnans befintliga funktioner, aldrig tabellerna direkt:
   `ApprovalQueue.approve/reject`, `ControlStops.place/lift/place_all` och `KillSwitch.engage/vote_release`,
4. loggar resultatet i revisionsloggen med grundarens mejl (`control.applied` eller `control.rejected`).

En ogiltig post avvisas och loggas; den stoppar aldrig de andra. D-081: en grundare räcker i simuleringen.
`run_agent_now` finns inte: kärnan saknar ett säkert sätt att köra en enskild agent, så knappen är skrivskyddad.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..monitoring import get_logger

log = get_logger("control")
QUEUE_PREFIX = "queue:"
MAX_AGE = timedelta(days=7)
TYPES = ("approve", "reject", "pause_agent", "resume_agent", "pause_all", "kill", "kill_release")
FIELDS = {"id", "type", "email", "founder", "at", "request", "agent", "note", "confirm"}


class Rejected(Exception):
    """Posten är ogiltig eller nekades av kärnan. Texten loggas i revisionsloggen."""


def parse_emails(text: str | None) -> dict[str, str]:
    """`ALLOWED_EMAILS` = "yorgo=a@x.se,robin=b@y.se" -> {mejl: grundare}. Poster utan namn ger ingen grundare."""
    out: dict[str, str] = {}
    for part in (text or "").split(","):
        name, sep, email = part.strip().partition("=")
        if sep and name.strip() and email.strip():
            out[email.strip().lower()] = name.strip().lower()
    return out


def validate(item, founders: frozenset[str], emails: dict[str, str], now: datetime) -> dict:
    """Returnerar den kontrollerade posten eller kastar Rejected. Ingenting i posten litas på utan kontroll."""
    if not isinstance(item, dict):
        raise Rejected("posten är inte ett objekt")
    if set(item) - FIELDS:
        raise Rejected(f"okända fält: {sorted(set(item) - FIELDS)}")
    kind = item.get("type")
    if kind not in TYPES:
        raise Rejected(f"okänd åtgärd {kind!r}")
    if not isinstance(item.get("id"), str) or not 8 <= len(item["id"]) <= 64:
        raise Rejected("id saknas eller har fel form")
    email = str(item.get("email") or "").lower()
    founder = str(item.get("founder") or "").lower()
    if founder not in founders:
        raise Rejected(f"{founder!r} är inte en grundare")
    if emails.get(email) != founder:
        raise Rejected("mejladressen hör inte till grundaren enligt ALLOWED_EMAILS")
    try:
        at = datetime.fromisoformat(str(item.get("at")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise Rejected("tidsstämpeln går inte att tolka") from exc
    if at.tzinfo is None or not timedelta(minutes=-5) <= now - at <= MAX_AGE:
        raise Rejected("posten är för gammal eller har en tid i framtiden")
    note = str(item.get("note") or "")[:300]
    clean = {"id": item["id"], "type": kind, "email": email, "founder": founder, "at": at.isoformat(), "note": note}
    if kind in ("approve", "reject"):
        if not isinstance(item.get("request"), int) or isinstance(item.get("request"), bool) or item["request"] < 1:
            raise Rejected("request måste vara förfrågans nummer")
        if kind == "reject" and not note.strip():
            raise Rejected("ett avslag kräver en motivering")
        clean["request"] = item["request"]
    if kind in ("pause_agent", "resume_agent"):
        if not isinstance(item.get("agent"), str) or not item["agent"].strip():
            raise Rejected("agent saknas")
        clean["agent"] = item["agent"].strip()
    if kind == "kill" and item.get("confirm") != "KILL":
        raise Rejected("nödstoppet kräver bekräftelsen KILL")
    if kind == "kill_release":
        if item.get("confirm") != "RELEASE":
            raise Rejected("återstarten kräver bekräftelsen RELEASE")
        if not note.strip():
            raise Rejected("återstarten kräver en motivering")
    return clean


def apply(system, gov, item: dict) -> dict:
    """Utför en kontrollerad post via kärnan. Returnerar ett kort resultat; kärnans nekanden blir Rejected."""
    founder, kind = item["founder"], item["type"]
    reason = f"Command Center ({item['id']})" + (f": {item['note']}" if item["note"] else "")
    try:
        if kind == "approve":
            done = gov.queue.approve(founder, item["request"], item["note"])
            return {"request": done.request_id, "status": done.status.value}
        if kind == "reject":
            done = gov.queue.reject(founder, item["request"], item["note"])
            return {"request": done.request_id, "status": done.status.value}
        # Paus är ett kontrollstopp (SR-05), inte en avstängning: livscykeln ändras bara genom ett beslutat
        # ärende (SR-17). Ett stopp nekar agentens alla verktyg tills en grundare häver det.
        if kind == "pause_agent":
            if _agent_stops(system, item["agent"]):
                raise Rejected(f"{item['agent']} är redan pausad")
            stop = system.stops.place(founder, "agent", item["agent"], reason)
            return {"agent": item["agent"], "stop": stop.stop_id}
        if kind == "resume_agent":
            stops = _agent_stops(system, item["agent"])
            if not stops:
                raise Rejected(f"{item['agent']} har inget aktivt stopp att häva")
            return {"agent": item["agent"], "lifted": [system.stops.lift(founder, s.stop_id, reason).stop_id for s in stops]}
        if kind == "pause_all":
            return {"paused": [s.scope_value for s in system.stops.place_all(founder, reason)]}
        if kind == "kill_release":  # kärnan kräver en hel revisionskedja och en grundare (D-030, D-049)
            state = system.kill.vote_release(founder, reason)
            return {"kill_switch": state.engaged}
        state = system.kill.engage(founder, reason)
        return {"kill_switch": state.engaged}
    except Rejected:
        raise
    except Exception as exc:  # noqa: BLE001 — kärnans nekanden (ApprovalError, RegistryError, KillSwitchError ...)
        raise Rejected(f"{type(exc).__name__}: {exc}") from exc


def _agent_stops(system, agent_id: str):
    return [s for s in system.stops.active() if s.scope_kind == "agent" and s.scope_value == agent_id]


def _handled(system) -> set[str]:
    """Id:n som redan är behandlade enligt revisionsloggen, så att en post aldrig utförs två gånger."""
    rows = system.db.connection.execute(
        "SELECT details FROM audit_log WHERE action IN ('control.applied', 'control.rejected')")
    return {json.loads(d).get("id") for (d,) in rows}


def process(system, gov, raw_items: list[tuple[str, bytes | None]], founders, emails, now: datetime | None = None) -> dict:
    """Behandlar posterna i ordning. Returnerar {"applied": [...], "rejected": [...], "duplicates": [...]}."""
    now = now or datetime.now(UTC)
    seen = _handled(system)
    out = {"applied": [], "rejected": [], "duplicates": []}
    for key, raw in raw_items:
        try:
            item = json.loads(raw or b"null")
        except ValueError:
            item = None
        item_id = item.get("id") if isinstance(item, dict) and isinstance(item.get("id"), str) else key
        if item_id in seen:
            out["duplicates"].append(item_id)
            continue
        seen.add(item_id)
        try:
            clean = validate(item, frozenset(founders), emails, now)
            result = apply(system, gov, clean)
        except Rejected as exc:
            actor = item.get("founder") if isinstance(item, dict) and item.get("founder") in founders else "system:control"
            system.audit.append(actor, "control.rejected", {
                "id": item_id, "type": str(item.get("type"))[:40] if isinstance(item, dict) else None,
                "email": str(item.get("email"))[:120] if isinstance(item, dict) else None, "reason": str(exc)[:300]})
            log.warning("kontrollposten %s avvisades: %s", item_id, exc)
            out["rejected"].append({"id": item_id, "reason": str(exc)})
            continue
        system.audit.append(clean["founder"], "control.applied", {
            "id": clean["id"], "type": clean["type"], "email": clean["email"], "queued_at": clean["at"],
            "target": clean.get("request") or clean.get("agent"), "result": result})
        out["applied"].append({"id": clean["id"], "type": clean["type"], "result": result})
    return out


def open_core(config, db, config_dir):
    """Hela systemet (nödstopp, register) och godkännandekön, byggda som i resten av kärnan."""
    from ..governance.cli import build
    from ..simulation.market import SimClock
    from ..simulation.run import stored_run
    from ..system import build_system

    run = stored_run(db)
    system = build_system(config, db, config_dir, clock=SimClock(run["start_date"]) if run else None)
    return system, build(config, db, config_dir)


def ingest(config_dir: Path, kv=None, emails: dict[str, str] | None = None) -> int:
    """CLI: läser och tömmer kön i KV. Avslutar med 0 även när poster avvisas; 1 bara när kön inte går att läsa."""
    from .. import runtime
    from .publish import KV

    try:
        config = runtime._load(config_dir, console=False)
    except runtime.StartupError as exc:
        return runtime._fail(exc)
    kv = kv or KV.from_env()
    if kv is None:
        print("control ingest: KV är inte konfigurerat; inget att göra")
        return 0
    emails = parse_emails(os.environ.get("ALLOWED_EMAILS")) if emails is None else emails
    try:
        keys = kv.keys(QUEUE_PREFIX)
        items = [(key, kv.get(key)) for key in keys]
    except Exception as exc:  # noqa: BLE001
        log.error("kön kunde inte läsas: %s", type(exc).__name__)
        print(f"FEL: kön kunde inte läsas ({type(exc).__name__})", file=sys.stderr)
        return 1
    with runtime._open(config) as db:
        system, gov = open_core(config, db, config_dir)
        result = process(system, gov, items, config.system.founders, emails)
        ok = system.audit.verify().ok
    for key in keys:  # posten är loggad; går den inte att ta bort hoppas den över nästa gång (samma id)
        try:
            kv.delete(key)
        except Exception as exc:  # noqa: BLE001
            log.error("kunde inte ta bort %s ur kön: %s", key, type(exc).__name__)
    print(f"control ingest: {len(result['applied'])} utförda, {len(result['rejected'])} avvisade, "
          f"{len(result['duplicates'])} dubbletter, revisionslogg {'OK' if ok else 'TRASIG'}")
    for r in result["rejected"]:
        print(f"  avvisad {r['id']}: {r['reason']}")
    return 0 if ok else 1
