"""`aie daily-cycle`: en företagscykel per dygn (§56), körs av GitHub Actions (Fas 8).

1. **Nödstopp:** finns filen `--kill-file` (t.ex. `docs/KILL-SWITCH`) slås nödstoppet på i databasen, med
   skälet i filen. Då gör agenterna ingenting, men rapporterna skrivs ändå. Tas filen bort släpps ett
   nödstopp som filen har satt (skälet börjar med `repo:`); ett nödstopp som en grundare satt släpps aldrig här.
2. **Cykeln:** en simulerad dag (SIM): agenterna samlar resultat, granskar ekonomin, utvärderar initiativ,
   risker och prioriteringar och fattar beslut genom samma spärrar som alltid. Skyddat läge och stop-loss
   gäller. Groqs kvot räknas i databasen; när den är slut pausas agenterna (ingen betald reserv).
3. **Rapporter:** daglig rapport (§57) i `<out>/daily/`, och på måndagar en periodisk rapport (§58) för
   veckan i `<out>/periodic/`.
4. **Instrumentpanelen:** `status.json` (bara offentliga data).
5. **Grundarna:** väntar något på ett grundarbeslut skrivs en kort notis i `QUESTIONS-FOR-FOUNDERS.md`.
"""

from __future__ import annotations

import contextlib
import io
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .. import runtime

NOTICE_START = "<!-- daily-cycle:start -->"
NOTICE_END = "<!-- daily-cycle:end -->"


def _kill(system, founder: str, kill_file: Path | None) -> str:
    state = system.kill.state()
    if kill_file is not None and kill_file.is_file():
        if not state.engaged:
            reason = "repo: " + (kill_file.read_text(encoding="utf-8").strip() or "nödstopp via fil")
            system.kill.engage(founder, reason[:300])
        return "på"
    if state.engaged and (state.reason or "").startswith("repo:"):
        system.kill.vote_release(founder, "filen för nödstopp är borttagen")
        return "släppt"
    return "på" if state.engaged else "av"


def pending_items(system) -> list[str]:
    items = []
    rows = system.db.connection.execute(
        "SELECT request_id, kind, reason FROM approval_requests WHERE status = 'pending' ORDER BY request_id").fetchall()
    items += [f"godkännandekön #{rid} ({kind}): {reason[:120]}" for rid, kind, reason in rows]
    if system.spend_approvals is not None:
        items += [f"utgift #{a.approval_id} {a.department}/{a.initiative}" for a in system.spend_approvals.pending()]
    if system.kill.state().engaged:
        items.append("nödstoppet är på")
    if system.protected.state().protected:
        items.append("skyddat läge är på: " + "; ".join(system.protected.state().reasons)[:200])
    return items


def update_questions(path: Path, items: list[str], today: str) -> bool:
    """Skriver eller tar bort notisen. Returnerar True om filen ändrades."""
    text = path.read_text(encoding="utf-8") if path.is_file() else "# Frågor till grundarna\n"
    block = ""
    if items:
        block = (f"{NOTICE_START}\n## Väntar på grundarbeslut (daglig cykel {today})\n"
                 + "".join(f"- {i}\n" for i in items) + f"{NOTICE_END}\n")
    if NOTICE_START in text:
        head, rest = text.split(NOTICE_START, 1)
        new = head + block + rest.split(NOTICE_END, 1)[1].lstrip("\n")
    else:
        new = text.rstrip("\n") + "\n\n" + block if block else text
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def run(config_dir: Path, founder: str, agents: str, out: Path, dashboard: Path, questions: Path,
        kill_file: Path | None, scenario: str = "normal", today: date | None = None) -> int:
    from ..reporting.daily import daily_report
    from ..reporting.periodic import periodic_report
    from ..simulation.cli import simulate
    from ..simulation.market import SimClock
    from ..simulation.run import stored_run
    from ..system import build_system
    from .export import build_status, write_status

    today = today or datetime.now(UTC).date()
    config = runtime._load(config_dir, console=False)
    with runtime._open(config) as db:
        run_ = stored_run(db)
        system = build_system(config, db, config_dir, clock=SimClock(run_["start_date"]) if run_ else None)
        kill = _kill(system, founder, kill_file)
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        action = "resume" if run_ else "start"
        code = simulate(config_dir, action, scenario if action == "start" else None, founder, 1, agents)
    print(log.getvalue(), end="")
    with runtime._open(config) as db:
        run_ = stored_run(db)
        system = build_system(config, db, config_dir, clock=SimClock(run_["start_date"]) if run_ else None)
        days = sorted({e.recorded_at[:10] for e in system.ledger.entries(system.currency)})
        written = []
        if days:
            (out / "daily").mkdir(parents=True, exist_ok=True)
            path = out / "daily" / f"{days[-1]}.md"
            path.write_text(daily_report(system, days[-1]).render(), encoding="utf-8")
            written.append(path)
            if today.weekday() == 0:
                start = max(days[0], (date.fromisoformat(days[-1]) - timedelta(days=6)).isoformat())
                (out / "periodic").mkdir(parents=True, exist_ok=True)
                path = out / "periodic" / f"{start}--{days[-1]}.md"
                path.write_text(periodic_report(system, start, days[-1]).render(), encoding="utf-8")
                written.append(path)
        write_status(build_status(system), dashboard)
        changed = update_questions(questions, pending_items(system), today.isoformat())
    print(f"Nödstopp: {kill}. Simuleringen: kod {code}. Rapporter: {', '.join(map(str, written)) or 'inga'}. "
          f"Instrumentpanel: {dashboard}. Grundarnotis {'uppdaterad' if changed else 'oförändrad'}.")
    return code
