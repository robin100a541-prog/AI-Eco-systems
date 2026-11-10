"""`py -m aie notify run|daily`. Avslutar alltid med 0 när en kanal fallerar: notiser får aldrig stoppa agenterna."""
from __future__ import annotations

import json
from pathlib import Path

from ..monitoring import get_logger
from .channels import Channels
from .triggers import collect

log = get_logger("notify")


def run(config_dir: Path, channels: Channels | None = None) -> int:
    """Skickar larm för det som hänt sedan förra gången. ntfy får bara de generiska texterna."""
    from .. import runtime
    from ..audit import AuditLog

    try:
        config = runtime._load(config_dir, console=False)
    except runtime.StartupError as exc:
        return runtime._fail(exc)
    channels = channels or Channels.from_env()
    with runtime._open(config) as db:
        alerts, record = collect(db)
        results = {"ntfy": "skipped", "email": "skipped"}
        if alerts:
            results["ntfy"] = _worst(channels.push("Command Center", a.generic) for a in alerts)
            body = "\n\n".join(f"{a.generic} ({a.count})\n{a.detail}" for a in alerts)
            results["email"] = channels.email(f"Command Center: {len(alerts)} alert(s)", body + "\n\nOpen Command Center for details.")
        # Markera som aviserat bara när något faktiskt skickades. Annars försöker nästa körning igen (till exempel
        # när hemligheterna läggs in senare), och en tyst körning lämnar inget spår i revisionsloggen.
        if "sent" in results.values():
            AuditLog(db).append("system:notify", "notify.sent", {**record, "channels": results})
    print(f"notify run: {len(alerts)} larm ({', '.join(a.kind for a in alerts) or 'inga'}), "
          f"ntfy {results['ntfy']}, e-post {results['email']}")
    return 0


def _worst(results) -> str:
    seen = list(results)
    for state in ("failed", "sent", "skipped"):
        if state in seen:
            return state
    return "skipped"


def summary_text(snapshot: dict) -> str:
    """Den dagliga sammanfattningen, byggd bara ur snapshoten (samma siffror som Command Center visar)."""
    cur = snapshot["currency"]
    e = snapshot["economy"]

    def money(metric) -> str:
        v = (metric or {}).get("value")
        return "N/A" if v is None else f"{v / 100:,.2f} {cur}".replace(",", " ")

    agents = snapshot["agents"]["items"]
    pending = [a for a in snapshot["approvals"]["items"] if a["status"] == "pending"]
    blocks = sum(b["count"] for b in snapshot["blocks_today"]["items"])
    lines = [
        f"Command Center daily summary ({snapshot['generated_at'][:16].replace('T', ' ')} UTC, {cur})",
        "",
        f"System mode: {snapshot['system']['mode']['value']}",
        f"Audit chain: {'verified' if snapshot['audit_chain']['ok'] else 'BROKEN'} ({snapshot['audit_chain']['length']} entries)",
        f"Gross revenue: {money(e.get('revenue_gross'))}",
        f"Net profit (realized): {money(e.get('net_profit_realized'))}",
        f"Tax reserve: {money(e.get('tax_reserve'))}",
        f"Available capital: {money(e.get('disposable_capital'))}",
        f"Agents: {sum(1 for a in agents if a['status'] == 'working')} working, "
        f"{sum(1 for a in agents if a.get('paused'))} paused, {len(agents)} registered",
        f"Waiting for a founder: {len(pending)}",
        f"Blocked actions today: {blocks}",
    ]
    for a in pending[:10]:
        lines.append(f"  - request #{a['id']}: {a.get('goal') or a['reason']} ({a['amount'] / 100:.2f} {a['currency']})")
    return "\n".join(lines)


def daily(config_dir: Path, channels: Channels | None = None, kv=None) -> int:
    """Skickar sammanfattningen med e-post. Snapshoten hämtas ur KV; utan KV eller snapshot skickas ingenting."""
    from ..dashboard.publish import KV

    channels = channels or Channels.from_env()
    kv = kv or KV.from_env()
    snapshot = None
    if kv is not None:
        try:
            raw = kv.get("snapshot:latest")
            snapshot = json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001
            log.error("snapshoten kunde inte hämtas ur KV: %s", type(exc).__name__)
    if snapshot is None:
        print("notify daily: ingen snapshot att sammanfatta; inget skickat")
        return 0
    result = channels.email("Command Center: daily summary", summary_text(snapshot))
    print(f"notify daily: e-post {result}")
    return 0
