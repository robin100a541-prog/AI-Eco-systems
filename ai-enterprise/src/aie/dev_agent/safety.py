"""Säkerhet för utvecklaragenten (Fas 8, masterprompten 2026-10-30).

- **Högst `MAX_MERGES_PER_DAY` automatiska merges per dygn (UTC).** Workflowen räknar dagens mergade PR:er
  från grenar `claude/dev-agent-*` och hoppar över körningen när taket är nått.
- **Efter varje merge** körs hela sviten på main (`dev-agent-guard.yml`). Blir den röd backas mergen
  automatiskt med en revert-PR, och en incident loggas (ärende plus rad i `docs/bot-reports/incidents.md`).
- **Veckosammanfattning:** `weekly_summary` läser veckans rapporter och skrivs till
  `docs/bot-reports/weekly-ÅÅÅÅ-VV.md`.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

MAX_MERGES_PER_DAY = 4
BRANCH_PREFIX = "claude/dev-agent-"
_REPORT = re.compile(r"^dev-agent-(\d{4}-\d{2}-\d{2})-(\d{4})\.md$")


def merges_today(prs: list[dict], today: str) -> int:
    """Antal PR:er från agentens grenar som mergades i dag (UTC). `prs` är GitHubs PR-objekt."""
    return sum(1 for p in prs if (p.get("head") or {}).get("ref", "").startswith(BRANCH_PREFIX)
               and (p.get("merged_at") or "")[:10] == today)


def may_merge(prs: list[dict], today: str) -> bool:
    return merges_today(prs, today) < MAX_MERGES_PER_DAY


def week_of(day: str) -> tuple[int, int]:
    iso = date.fromisoformat(day).isocalendar()
    return iso[0], iso[1]


def weekly_summary(reports_dir: Path, year: int, week: int) -> str:
    runs, done, questions, tests, failed = [], [], [], [], 0
    for path in sorted(Path(reports_dir).glob("dev-agent-*.md")):
        m = _REPORT.match(path.name)
        if not m or week_of(m.group(1)) != (year, week):
            continue
        runs.append(path.name)
        section = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            elif section == "Gjort" and line.startswith("- BL-"):
                done.append(line[2:].split(" Klart när:")[0])
            elif section == "Frågor till grundarna" and line.startswith("- "):
                questions.append(line[2:])
            elif section == "Tester" and "Ran" in line:
                tests.append(line.strip("` "))
                failed += "OK" not in line
    lines = [f"# Utvecklaragenten vecka {year}-{week:02d}", "",
             f"- Körningar: {len(runs)}", f"- Klara punkter: {len(done)}",
             f"- Testkörningar som inte var gröna: {failed}", f"- Nya frågor till grundarna: {len(questions)}", ""]
    if done:
        lines += ["## Klart"] + [f"- {d}" for d in done] + [""]
    if questions:
        lines += ["## Frågor"] + [f"- {q}" for q in questions] + [""]
    lines += ["## Rapporter"] + ([f"- {r}" for r in runs] or ["- inga körningar"])
    return "\n".join(lines) + "\n"


def write_weekly(reports_dir: Path, day: str) -> Path:
    year, week = week_of(day)
    path = Path(reports_dir) / f"weekly-{year}-{week:02d}.md"
    path.write_text(weekly_summary(reports_dir, year, week), encoding="utf-8")
    return path
