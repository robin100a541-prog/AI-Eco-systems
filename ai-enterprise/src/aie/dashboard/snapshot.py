"""Snapshoten för Command Center (Del 1, D-085): allt som dashboarden visar, i ett JSON-dokument.

Regler (docs/command-center/DATA.md):
- Varje siffra är `{"value", "source", "as_of"}`. `source` är tabellen eller kärnfunktionen som gav värdet.
  Saknas data är `value` None, och gränssnittet visar "N/A". Inget räknas fram i webbläsaren.
- Pengar räknas bara med kärnans funktioner (`compute_result`, `capital_position`, `TaxEngine`), så snapshoten
  är exakt lika med revisionens omräkning (`recompute`, ER-16). Testet `test_snapshot` kontrollerar det.
- Brutto och netto hålls isär: brutto är summan av `revenue` som är `settled`; netto är brutto minus
  återbetalningar, kostnader och avgifter. `pending` räknas aldrig.
- Vitlistan och `check_public` från `export.py` gäller fortfarande: inga hemligheter, prompter eller modellsvar.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta

from .. import __version__
from ..ledger import EntryType, compute_result
from ..ledger.ledger import Status
from ..monitoring import mask_secrets
from .export import check_public, ensure_names, scout_counts

SCHEMA = "aie.snapshot/1"
MAX_LEDGER = 500
MAX_EVENTS = 300

# Revisionsloggens åtgärder -> händelsetyp i Activity. Bara åtgärder som finns i koden (DATA.md avsnitt 4).
EVENT_TYPES = {
    "ledger.recorded": "transaction recorded", "ledger.status": "transaction completed",
    "llm.provider_failed": "error", "llm.unavailable": "error", "incident.opened": "error",
    "simulation.invalid_actions": "error", "dev.check_failed": "error",
    "tool.denied": "blocked", "budget.blocked": "blocked", "ledger.duplicate_refused": "blocked",
    "approval.requested": "approval", "approval.decided": "approval",
    "kill.engaged": "kill switch", "kill.released": "kill switch",
    "mode.protected_entered": "protected mode", "mode.protected_exited": "protected mode",
    "simulation.day": "run completed", "system.start": "system", "system.stop": "system",
    "control.applied": "founder control", "control.rejected": "founder control",
    "stop.placed": "agent stopped", "stop.lifted": "agent started",
}


def metric(value, source: str, as_of: str) -> dict:
    return {"value": value, "source": source, "as_of": as_of}


def _has(db, table: str) -> bool:
    return db.connection.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None


def build_snapshot(system, config, config_dir, *, now: str | None = None, real_system=None,
                   commit: str | None = None) -> dict:
    """Bygger snapshoten ur företagets databas. `real_system` är pilotens databas (riktig valuta) om den finns."""
    from ..authorization import load_permissions

    at = now or datetime.now(UTC).isoformat(timespec="seconds")
    db = system.db
    currency = config.risk.currency
    entries = system.ledger.entries(currency)
    permissions = load_permissions(config_dir)
    agents = list(system.registry.agents())
    names = ensure_names(db, [a.agent_id for a in agents])
    audit = system.audit.verify()

    snap = {
        "schema": SCHEMA,
        "generated_at": at,
        "environment": config.system.environment,
        "currency": currency,
        "system": _system(system, db, at, commit),
        "economy": _economy(system, entries, currency, at),
        "economy_real": _economy(real_system, real_system.ledger.entries(real_system.currency),
                                 real_system.currency, at) if real_system is not None else None,
        "periods": _periods(entries, currency, at),
        "per_agent": _per_agent(entries, currency, at),
        "ledger": _ledger(entries, at),
        "agents": _agents(system, db, agents, names, permissions, at),
        "departments": _departments(permissions, agents, at),
        "approvals": _approvals(db, at),
        "risk_limits": _limits(config.risk, system, entries, at),
        "blocks_today": _blocks_today(db, at),
        "events": _events(db, at),
        "audit_chain": {"ok": audit.ok, "length": audit.checked if hasattr(audit, "checked") else _count(db, "audit_log"),
                        "first_bad_seq": audit.first_bad_seq, "source": "AuditLog.verify", "as_of": at},
        "quotas": _quotas(db, config_dir, at),
        "stops": {"items": [{"id": s.stop_id, "scope": s.scope_kind, "target": s.scope_value,
                             "reason": mask_secrets(s.reason)[:200], "placed_by": s.placed_by, "placed_at": s.placed_at}
                            for s in (system.stops.active() if getattr(system, "stops", None) is not None else ())],
                  "source": "ControlStops.active", "as_of": at},
        "tasks": _tasks(db, agents, at),
        "consultations": _consultations(db, at),
        "lessons": _rows(db, at, "lessons", "SELECT lesson_id, statement, scope, proposed_by, at FROM lessons "
                         "ORDER BY lesson_id DESC LIMIT 50", ("id", "statement", "scope", "by", "at")),
        "incidents": _rows(db, at, "incidents", "SELECT incident_id, source, title, reported_by, opened_at FROM incidents "
                           "ORDER BY incident_id DESC LIMIT 50", ("id", "source", "title", "by", "at")),
        "tax": _tax(system, currency, at),
        "scout": {"counts": scout_counts(db), "source": "scout_entries (senaste versionen per möjlighet)", "as_of": at},
        "rules": {
            "founders": sorted(config.system.founders),
            "approval_threshold": config.risk.human_approval_threshold.amount_minor
            if config.risk.human_approval_threshold is not None else None,
            "governance_tools": sorted(t for t in permissions.tools if t.startswith("governance.")),
            "source": "config/system.toml, config/risk_limits.toml, config/permissions.toml", "as_of": at,
        },
        # Bara om en kanal är konfigurerad (hemligheten finns i miljön), aldrig värdet (D-091).
        "notifications": {"ntfy": bool(os.environ.get("NTFY_TOPIC")),
                          "email": bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")),
                          "source": "miljön där snapshoten byggdes", "as_of": at},
    }
    check_snapshot(snap)
    return snap


def _count(db, table: str) -> int:
    return db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if _has(db, table) else 0


def _system(system, db, at: str, commit: str | None) -> dict:
    kill = system.kill.state()
    protected = system.protected.state().protected
    last = db.connection.execute(
        "SELECT timestamp, details FROM audit_log WHERE action = 'simulation.day' ORDER BY seq DESC LIMIT 1").fetchone()
    mode = "kill switch" if kill.engaged else ("protected" if protected else "normal")
    return {
        "mode": metric(mode, "KillSwitch.state, ProtectedMode.state", at),
        "kill_switch": metric(kill.engaged, "KillSwitch.state", at),
        "protected_mode": metric(protected, "ProtectedMode.state", at),
        "last_run": metric(last[0] if last else None, "audit_log: simulation.day", at),
        "last_run_day": metric(json.loads(last[1]).get("day") if last else None, "audit_log: simulation.day", at),
        "version": metric(__version__ + (f"+{commit[:7]}" if commit else ""), "aie.__version__, GITHUB_SHA", at),
        "database_bytes": metric(db.path.stat().st_size if db.path.exists() else None, "storlek på databasfilen", at),
    }


def _economy(system, entries, currency: str, at: str) -> dict:
    from ..budget.capital import capital_position

    if not entries:
        none = {k: metric(None, "ledger_entries (tom)", at) for k in (
            "revenue_gross", "refunds", "costs", "platform_fees", "net_profit_realized", "tax_reserve",
            "disposable_capital", "protected_reserve", "liquid")}
        return {**none, "preliminary": metric(None, "compute_result", at), "vat": None, "currency": currency}
    result = compute_result(entries, currency)
    reserved = system.tax.reserved_minor(currency)
    pos = capital_position(entries, system.budget._limits, reserved)
    vat = system.tax.vat_status()
    return {
        "currency": currency,
        "revenue_gross": metric(result.revenue_minor, "compute_result: revenue (settled)", at),
        "refunds": metric(result.refunds_minor, "compute_result: refund (settled)", at),
        "costs": metric(result.costs_minor, "compute_result: cost (settled)", at),
        "platform_fees": metric(result.fees_minor, "compute_result: fee (settled)", at),
        "net_profit_realized": metric(result.net_minor, "compute_result: net", at),
        "preliminary": metric(list(result.reasons) if result.preliminary else [], "compute_result: reasons", at),
        "tax_reserve": metric(reserved, "TaxEngine.reserved_minor", at),
        "liquid": metric(pos.liquid_minor, "capital_position: liquid", at),
        "disposable_capital": metric(pos.disposable_minor, "capital_position: disposable", at),
        "protected_reserve": metric(pos.reserve_minor, "capital_position: reserve (MINIMUM_RESERVE)", at),
        "vat": {"year": vat.year, "sales": metric(vat.sales_minor, "TaxEngine.vat_status", at),
                "threshold": metric(vat.threshold_minor, "TaxEngine.vat_status", at), "level": vat.level},
    }


def _day(e) -> str:
    return (e.occurred_on or e.recorded_at)[:10]


def _periods(entries, currency: str, at: str) -> dict:
    """Intäkt, kostnad och netto per dag, ISO-vecka och månad, varje period räknad med compute_result."""
    keys = {"day": _day, "week": lambda e: "%d-W%02d" % date.fromisoformat(_day(e)).isocalendar()[:2],
            "month": lambda e: _day(e)[:7]}
    out = {}
    for name, key in keys.items():
        groups: dict[str, list] = defaultdict(list)
        for e in entries:
            groups[key(e)].append(e)
        rows = []
        for period in sorted(groups):
            r = compute_result(tuple(groups[period]), currency)
            rows.append({"period": period, "revenue": r.revenue_minor, "cost": r.costs_minor + r.fees_minor + r.refunds_minor,
                         "net": r.net_minor})
        out[name] = {"items": rows[-60:], "source": "compute_result per period", "as_of": at}
    return out


def _per_agent(entries, currency: str, at: str) -> dict:
    """Per `recorded_by`, alltså den som bokförde. I SIM bokför `system:simulation`; det visas som det är."""
    groups: dict[str, list] = defaultdict(list)
    for e in entries:
        groups[e.recorded_by].append(e)
    rows = []
    for who in sorted(groups):
        r = compute_result(tuple(groups[who]), currency)
        rows.append({"agent": who, "revenue": r.revenue_minor, "cost": r.costs_minor + r.fees_minor + r.refunds_minor,
                     "net": r.net_minor})
    return {"items": rows, "source": "compute_result per ledger_entries.recorded_by", "as_of": at}


def _ledger(entries, at: str) -> dict:
    rows = [{"id": e.entry_id, "key": e.idempotency_key, "type": e.entry_type.value, "amount": e.amount_minor,
             "currency": e.currency, "status": e.status.value, "by": e.recorded_by, "initiative": e.initiative,
             "department": e.department, "date": _day(e), "recorded_at": e.recorded_at,
             "external_id": e.external_id} for e in entries]
    rows.sort(key=lambda r: r["id"], reverse=True)
    return {"items": rows[:MAX_LEDGER], "total": len(rows), "source": "Ledger.entries", "as_of": at}


def _agents(system, db, agents, names, permissions, at: str) -> dict:
    conn = db.connection
    calls = defaultdict(list)
    for ts, details in conn.execute("SELECT timestamp, details FROM audit_log WHERE action = 'llm.call' ORDER BY seq"):
        d = json.loads(details)
        if d.get("caller"):
            calls[d["caller"]].append((ts, d))
    outcomes = defaultdict(Counter)
    for (details,) in conn.execute("SELECT details FROM audit_log WHERE action = 'simulation.action'"):
        d = json.loads(details)
        if d.get("agent"):
            outcomes[d["agent"]]["done" if d.get("outcome") == "done" else "failed"] += 1
    for (details,) in conn.execute("SELECT details FROM audit_log WHERE action = 'tool.denied'"):
        d = json.loads(details)
        if d.get("agent_id"):
            outcomes[d["agent_id"]]["failed"] += 1
    tasks = {}
    for task_id, title, owner, status in conn.execute(
            "SELECT task_id, title, owner_id, status FROM tasks WHERE status IN ('assigned', 'in_progress', 'blocked') "
            "ORDER BY updated_at"):
        tasks[owner] = {"id": task_id, "title": title, "status": status}
    waiting = {r for (r,) in conn.execute("SELECT requested_by FROM approval_requests WHERE status = 'pending'")}
    stops = system.stops.active() if getattr(system, "stops", None) is not None else ()
    stopped_agents = {s.scope_value for s in stops if s.scope_kind == "agent"}
    stopped_departments = {s.scope_value for s in stops if s.scope_kind == "department"}
    rows = []
    for a in agents:
        mandate = permissions.roles.get(a.role)
        done, failed = outcomes[a.agent_id]["done"], outcomes[a.agent_id]["failed"]
        last = calls[a.agent_id][-1] if calls[a.agent_id] else None
        task = tasks.get(a.agent_id)
        rows.append({
            "id": a.agent_id, "name": names[a.agent_id], "role": a.role, "department": a.department,
            "level": mandate.level if mandate else None,
            "description": mandate.description if mandate else None,
            "lifecycle": a.state.value.lower(),
            "paused": a.agent_id in stopped_agents or a.department in stopped_departments,
            "status": "offline" if a.agent_id in stopped_agents or a.department in stopped_departments
            else _status(a.state.value.lower(), task, a.agent_id in waiting),
            "manager": a.manager_id,
            "task": task,
            "progress": None,  # framsteg registreras inte i kärnan; visas som N/A
            "model": f"{last[1].get('provider')}/{last[1].get('model')}" if last else None,
            "last_run": last[0] if last else None,
            "runs": len(calls[a.agent_id]),
            "actions_done": done, "actions_failed": failed,
            "success_rate": round(done / (done + failed), 4) if done + failed else None,
            "tools": sorted(mandate.tools) if mandate else [],
            "recent_runs": [{"at": t, "model": f"{d.get('provider')}/{d.get('model')}", "tokens": d.get("tokens"),
                             "data_class": d.get("data_class")} for t, d in calls[a.agent_id][-20:]][::-1],
        })
    return {"items": rows, "source": "AgentRegistry, ControlStops, audit_log (llm.call, simulation.action, tool.denied), tasks",
            "as_of": at}


def _status(lifecycle: str, task, waiting: bool) -> str:
    """Härlett ur verifierade data, regeln står i DATA.md. Okänt ger 'unknown', som inte visas som pill."""
    if lifecycle in ("suspended", "retired"):
        return "offline"
    if lifecycle not in ("active", "probation"):
        return "unknown"
    if task and task["status"] == "blocked":
        return "blocked"
    if waiting:
        return "waiting"
    if task:
        return "working"
    return "idle"


def _departments(permissions, agents, at: str) -> dict:
    deps: dict[str, dict] = {}
    for role, m in sorted(permissions.roles.items()):
        d = deps.setdefault(m.department, {"id": m.department, "roles": [], "agents": []})
        d["roles"].append(role)
    for a in agents:
        deps.setdefault(a.department, {"id": a.department, "roles": [], "agents": []})["agents"].append(a.agent_id)
    return {"items": list(deps.values()), "source": "config/permissions.toml, AgentRegistry", "as_of": at}


def _approvals(db, at: str) -> dict:
    conn = db.connection
    rows = []
    for rid, kind, task_id, dispute_id, by, reason, amount, cur, required, status, created in conn.execute(
            "SELECT request_id, kind, task_id, dispute_id, requested_by, reason, amount_minor, currency, "
            "required_approvals, status, created_at FROM approval_requests ORDER BY request_id DESC LIMIT 200"):
        votes = [{"founder": f, "verdict": v, "note": n, "at": t} for f, v, n, t in conn.execute(
            "SELECT founder, verdict, note, at FROM approval_votes WHERE request_id = ? ORDER BY id", (rid,))]
        opinions = []
        if task_id is not None and _has(db, "consultations"):
            # Ett samråd hör till förfrågan bara när ämnet uttryckligen pekar på uppgiften ("task:<id>").
            opinions = [{"by": a, "position": p, "text": mask_secrets(t or "")} for a, p, t in conn.execute(
                "SELECT o.agent_id, o.position, o.reasoning FROM consultation_opinions o JOIN consultations c "
                "ON c.consultation_id = o.consultation_id WHERE c.subject = ? ORDER BY o.id", (f"task:{task_id}",))]
        payload = conn.execute("SELECT payload FROM approval_requests WHERE request_id = ?", (rid,)).fetchone()[0]
        draft = json.loads(payload) if payload else {}
        rows.append({"id": rid, "kind": kind, "task": task_id, "dispute": dispute_id, "requested_by": by,
                     "reason": reason, "amount": amount, "currency": cur, "required": required, "status": status,
                     "created_at": created, "votes": votes,
                     "goal": draft.get("chosen_action"), "risk_class": draft.get("risk_class"),
                     "max_loss": draft.get("budget_minor"), "stop_conditions": draft.get("stop_conditions"),
                     "opinions": [o for o in opinions if o["position"] != "object"],
                     "objections": [o for o in opinions if o["position"] == "object"]})
    return {"items": rows, "source": "approval_requests, approval_votes, consultation_opinions", "as_of": at}


def _limits(limits, system, entries, at: str) -> dict:
    from ..budget.capital import capital_position

    pos = capital_position(entries, limits) if entries else None
    worst = None
    by_init = defaultdict(list)
    for e in entries:
        by_init[e.initiative].append(e)
    if by_init:
        worst = min(compute_result(tuple(v), limits.currency).net_minor for v in by_init.values())
    used = {  # MINIMUM_RESERVE är ett golv, inte ett tak: ingen "användning" visas för den
        "max_committed_capital": pos.committed_minor if pos else None,
        "max_single_experiment_loss": max(0, -worst) if worst is not None else None,
    }
    rows = []
    for name in ("start_capital", "minimum_reserve", "max_total_drawdown", "max_single_experiment_loss",
                 "max_department_budget", "max_single_transaction", "max_committed_capital",
                 "max_allowed_unverified_spend", "human_approval_threshold", "reinvestment_policy",
                 "api_monthly_cap", "max_platform_revenue_share", "min_active_platforms"):
        value = getattr(limits, name, None)
        if value is None:
            limit = None
        elif hasattr(value, "amount_minor"):
            limit = value.amount_minor
        else:
            limit = str(value)
        rows.append({"name": name.upper(), "limit": limit, "used": used.get(name)})
    return {"items": rows, "source": "config/risk_limits.toml, capital_position, compute_result per initiative",
            "as_of": at}


def _blocks_today(db, at: str) -> dict:
    today = at[:10]
    rows = Counter()
    for action, details in db.connection.execute(
            "SELECT action, details FROM audit_log WHERE action IN ('tool.denied', 'budget.blocked', "
            "'ledger.duplicate_refused') AND substr(timestamp, 1, 10) = ?", (today,)):
        d = json.loads(details)
        rows[(action, d.get("tool") or d.get("reason", "")[:60])] += 1
    return {"items": [{"step": a, "what": w, "count": n} for (a, w), n in rows.most_common()],
            "source": "audit_log", "as_of": at}


def _events(db, at: str) -> dict:
    conn = db.connection
    out = []
    for seq, ts, actor, action, details, h in conn.execute(
            "SELECT seq, timestamp, actor, action, details, hash FROM audit_log ORDER BY seq DESC LIMIT ?",
            (MAX_EVENTS * 3,)):
        kind = EVENT_TYPES.get(action)
        if kind is None:
            continue
        d = json.loads(details)
        if action == "ledger.recorded" and d.get("entry_type") == "revenue":
            kind = "revenue recorded"
        if action == "ledger.status" and d.get("status") != "settled":
            continue
        out.append({"id": f"audit:{seq}", "seq": seq, "at": ts, "actor": actor, "action": action, "type": kind,
                    "hash": h[:16]})
        if len(out) >= MAX_EVENTS:
            break
    if _has(db, "agent_state_changes"):
        for cid, agent, new, at_ in conn.execute(
                "SELECT id, agent_id, new_state, at FROM agent_state_changes ORDER BY id DESC LIMIT 50"):
            new = (new or "").lower()
            if new in ("active", "suspended", "retired"):
                out.append({"id": f"agent:{cid}", "seq": None, "at": at_, "actor": agent, "action": f"agent.{new}",
                            "type": "agent started" if new == "active" else "agent stopped", "hash": None})
    if _has(db, "task_events"):
        for tid, task, actor, at_ in conn.execute(
                "SELECT id, task_id, actor, at FROM task_events WHERE new_status = 'done' ORDER BY id DESC LIMIT 50"):
            out.append({"id": f"task:{tid}", "seq": None, "at": at_, "actor": actor, "action": f"task.done:{task}",
                        "type": "task completed", "hash": None})
    out.sort(key=lambda e: e["at"], reverse=True)
    return {"items": out[:MAX_EVENTS], "source": "audit_log, agent_state_changes, task_events", "as_of": at}


def _quotas(db, config_dir, at: str) -> dict:
    import tomllib
    from pathlib import Path

    path = Path(config_dir) / "providers.toml"
    providers = tomllib.loads(path.read_text(encoding="utf-8")).get("providers", []) if path.exists() else []
    today = db.connection.execute("SELECT MAX(day) FROM provider_usage").fetchone()[0] if _has(db, "provider_usage") else None
    usage = {p: (c, t) for p, c, t in db.connection.execute(
        "SELECT provider, calls, tokens FROM provider_usage WHERE day = ?", (today,))} if today else {}
    rows = [{"provider": p["name"], "model": p.get("model"), "day": today, "calls": usage.get(p["name"], (0, 0))[0],
             "calls_limit": p.get("daily_calls"), "tokens": usage.get(p["name"], (0, 0))[1],
             "tokens_limit": p.get("daily_tokens")} for p in providers]
    return {"items": rows, "source": "provider_usage, config/providers.toml", "as_of": at}


def _rows(db, at: str, table: str, sql: str, fields: tuple[str, ...]) -> dict:
    items = [dict(zip(fields, r)) for r in db.connection.execute(sql)] if _has(db, table) else []
    for item in items:
        for k, v in item.items():
            if isinstance(v, str):
                item[k] = mask_secrets(v)[:300]
    return {"items": items, "source": table, "as_of": at}


def _tasks(db, agents, at: str) -> dict:
    dept = {a.agent_id: a.department for a in agents}
    rows = [{"id": i, "title": mask_secrets(t)[:200], "owner": o, "department": dept.get(o), "status": st, "updated_at": u}
            for i, t, o, st, u in db.connection.execute(
                "SELECT task_id, title, owner_id, status, updated_at FROM tasks ORDER BY task_id DESC LIMIT 100")]
    return {"items": rows, "source": "tasks", "as_of": at}


def _consultations(db, at: str) -> dict:
    if not _has(db, "consultations"):
        return {"items": [], "source": "consultations", "as_of": at}
    rows = []
    for cid, subject, opened_by, risk, opened_at in db.connection.execute(
            "SELECT consultation_id, subject, opened_by, risk_class, opened_at FROM consultations "
            "ORDER BY consultation_id DESC LIMIT 50"):
        opinions = [{"by": a, "role": r, "position": p} for a, r, p in db.connection.execute(
            "SELECT agent_id, role, position FROM consultation_opinions WHERE consultation_id = ? ORDER BY id", (cid,))]
        rows.append({"id": cid, "subject": mask_secrets(subject)[:200], "opened_by": opened_by, "risk_class": risk,
                     "opened_at": opened_at, "opinions": opinions})
    return {"items": rows, "source": "consultations, consultation_opinions", "as_of": at}


def _tax(system, currency: str, at: str) -> dict:
    position = system.tax.position(currency)
    rows = [{"track": r.track, "year": r.year, "basis": r.gross_minor, "rate_bp": r.rate_bp,
             "liability": r.liability_minor, "paid": r.paid_minor, "reserved": r.reserved_minor} for r in position.rows]
    owners = Counter()
    for owners_text, n in system.db.connection.execute(
            "SELECT owners, COUNT(*) FROM tax_assignments GROUP BY owners") if _has(system.db, "tax_assignments") else []:
        owners[owners_text or "unassigned"] += n
    # Skatt per grundare: bara när alla poster har samma fördelning (baspunkter per grundare i tax_assignments),
    # annars None. Ingen fördelning gissas.
    per_founder = None
    if len(owners) == 1:
        try:
            split = json.loads(next(iter(owners)))
            total = sum(r["reserved"] for r in rows)
            per_founder = [{"founder": f, "share_bp": bp, "reserved": total * bp // 10_000} for f, bp in sorted(split.items())]
        except (ValueError, AttributeError):
            per_founder = None
    return {"items": rows, "per_founder": per_founder,
            "owners": [{"owners": o, "entries": n} for o, n in owners.most_common()],
            "untracked_entries": len(position.untracked), "source": "TaxEngine.position, tax_assignments", "as_of": at}


def check_snapshot(value) -> None:
    """Vitlistan för agentfält och kontrollen mot hemligheter i `export.py` (DR-13, SR-10)."""
    check_public(value)


def age_hours(snapshot: dict, now: datetime | None = None) -> float:
    at = datetime.fromisoformat(snapshot["generated_at"])
    return ((now or datetime.now(UTC)) - at) / timedelta(hours=1)


__all__ = ["build_snapshot", "check_snapshot", "metric", "SCHEMA", "EVENT_TYPES", "age_hours", "EntryType", "Status"]
