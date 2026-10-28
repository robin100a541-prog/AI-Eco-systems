"""Utvecklaragentens skötsel av `docs/BOT-BACKLOG.md` (D-050).

- En punkt utan kontroll (`Klart när:` med en giltig kontroll ur `verify.py`) skrivs om så att den går
  att bevisa (`add_check`).
- I slutet av en körning föreslår modellen högst tre nya, små punkter ur koden den läste. Bara punkter
  med en giltig kontroll läggs till, och dubbletter hoppas över (`add_items`). Förslag som rör skyddade
  filer, CI, konfiguration, pengar, riktiga konton eller nya funktioner blir i stället frågor till
  grundarna (`classify`), eftersom bara de får bestämma om sådant (CONSTITUTION.md, ROADMAP.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .patch import FORBIDDEN_PREFIXES, PROTECTED_FILES
from .verify import Check, checks_in

BACKLOG_FILE = "docs/BOT-BACKLOG.md"
MAX_NEW_ITEMS = 3
MAX_OPEN_ITEMS = 12  # fylls inte på när så många öppna punkter redan går att bevisa
CATEGORIES = {
    "1": "buggar",
    "2": "kravtäckning",
    "3": "säkerhet",
    "4": "kodkvalitet",
    "5": "dokumentation",
}
_PROPOSAL = re.compile(r"^\s*-\s*\[ \]\s*\((\d)\s*([^)]*)\)\s*(.+?)\s*$")
_ITEM = re.compile(r"^- \[ \] (BL-(\d+)) (.*?)\s*— öppen\s*$")
# Sådant bara grundarna beslutar om: pengar, riktiga konton och kunder, nya funktioner.
_FOUNDER_ONLY = re.compile(
    r"pengar|betalning|betala|faktur|\bbank|kortnummer|\bkonto|account|payment|stripe|paypal|"
    r"\bkund(er|en|erna)?\b|riktiga (pengar|konton|kunder)|produktion|publicer|"
    r"ny funktion|nya funktioner|feature",
    re.IGNORECASE,
)

CHECK_HELP = (
    "Kontroller (exakt en av dessa former, inom backticks):\n"
    "`ruff <fil> [REGEL]` (ruff hittar inget), `test tests.unit.test_x.Klass.test_y` (testet går "
    "igenom), `flaky-test <test-id>` (3 gånger i rad), `verifies <KRAV-ID>` (ett test märkt "
    "'Verifies <KRAV-ID>' finns och går igenom), `grep <fil> <text>` (filen innehåller texten), "
    "`!grep <fil> <text>` (filen innehåller inte texten). Filer anges relativt till ai-enterprise/."
)


@dataclass(frozen=True, slots=True)
class Proposal:
    priority: str
    text: str  # inklusive "Klart när: `...`"
    checks: tuple[Check, ...]

    @property
    def line_body(self) -> str:
        return f"({self.priority} {CATEGORIES.get(self.priority, '?')}) {self.text}"


def parse_proposals(text: str, project: Path) -> list[Proposal]:
    """Modellens förslag: rader `- [ ] (P kategori) vad och var. Klart när: `kontroll``."""
    out = []
    for line in text.splitlines():
        m = _PROPOSAL.match(line)
        if not m:
            continue
        body = m.group(3).removesuffix("— öppen").strip()
        checks = checks_in(body, project)
        if checks:
            out.append(Proposal(m.group(1), body, checks))
    return out


def classify(proposal: Proposal) -> str:
    """ "backlog" om agenten själv får ta punkten, annars "founders" (blir en fråga till grundarna)."""
    if proposal.priority not in CATEGORIES:
        return "founders"  # prioritet 6 och annat: förberedelse av nya faser hör till grundarna
    text = proposal.text
    touched = [f"ai-enterprise/{c.arg.split(' ')[0]}" for c in proposal.checks]
    paths = re.findall(r"[\w./-]+\.(?:py|md|toml|yml)", text) + touched
    for path in paths:
        full = (
            path
            if path.startswith(("ai-enterprise/", ".github/"))
            else f"ai-enterprise/{path}"
        )
        if full in PROTECTED_FILES or full.startswith(FORBIDDEN_PREFIXES):
            return "founders"
    if "CONSTITUTION" in text or "DECISIONS" in text or _FOUNDER_ONLY.search(text):
        return "founders"
    return "backlog"


def _norm(text: str) -> str:
    text = text.split("Klart när:")[0]
    return " ".join(re.findall(r"\w+", text.lower()))


def open_items(project: Path) -> list[tuple[str, str]]:
    path = project / BACKLOG_FILE
    if not path.is_file():
        return []
    return [
        (m.group(1), m.group(3))
        for m in map(_ITEM.match, path.read_text(encoding="utf-8").splitlines())
        if m
    ]


def is_duplicate(project: Path, proposal: Proposal) -> bool:
    path = project / BACKLOG_FILE
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    existing = [_norm(line) for line in text.splitlines() if line.startswith("- [")]
    checks = {str(c) for c in proposal.checks}
    same_check = any(f"`{c}`" in text for c in checks)
    return _norm(proposal.text) in existing or same_check


def add_items(project: Path, proposals: list[Proposal]) -> list[str]:
    """Lägger till punkterna sist under "## Öppna". Returnerar de nya nycklarna (BL-NNN)."""
    path = project / BACKLOG_FILE
    if not proposals or not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    numbers = [int(n) for n in re.findall(r"\bBL-(\d+)", text)]
    keys, lines = [], []
    for i, proposal in enumerate(proposals, start=max(numbers, default=0) + 1):
        keys.append(f"BL-{i:03d}")
        lines.append(f"- [ ] BL-{i:03d} {proposal.line_body} — öppen")
    lines_text = "\n".join(lines) + "\n"
    if "\n## Pågår" in text:
        head, tail = text.split("\n## Pågår", 1)
        text = head.rstrip("\n") + "\n" + lines_text + "\n## Pågår" + tail
    else:
        text = text.rstrip("\n") + "\n" + lines_text
    path.write_text(text, encoding="utf-8")
    return keys


def clause_checks(project: Path, answer: str) -> tuple[Check, ...]:
    """Kontrollerna i modellens svar `Klart när: `...``, eller () om inga giltiga finns."""
    m = re.search(r"Klart när:.*", answer)
    return checks_in(m.group(0), project) if m else ()


def add_check(project: Path, key: str, checks: tuple[Check, ...]) -> str | None:
    """Skriver in `Klart när:` med kontrollerna i punkten `key`. Returnerar klausulen, eller None."""
    if not checks:
        return None
    clause = "Klart när: " + ", ".join(f"`{c}`" for c in checks)
    path = project / BACKLOG_FILE
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith(f"- [ ] {key} ") and line.rstrip().endswith("— öppen"):
            lines[i] = line.rstrip().removesuffix("— öppen").rstrip() + f" {clause} — öppen\n"
            path.write_text("".join(lines), encoding="utf-8")
            return clause
    return None
