"""Granskning av en ändring från en språkmodell innan den får röra repot (D-050).

Sök/ersätt-blocken (`edits.py`) görs om till en unified diff som granskas här.

En diff avvisas om den
- rör en skyddad fil (samma lista som checken `protected-files`), CI, all konfiguration eller
  utvecklaragentens egen kod och tester,
- ligger utanför `ai-enterprise/` eller har konstiga sökvägar (`..`, absoluta, binära patchar),
- tar bort en fil,
- är större än `MAX_CHANGED_LINES` ändrade rader,
- lägger till en import utanför standardbiblioteket (eller paketet `aie`),
- försvagar tester: tar bort en rad med `def test_` eller `assert` i `tests/`.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

MAX_CHANGED_LINES = 200

# Samma filer som .github/workflows/protected-files.yml skyddar.
PROTECTED_FILES = frozenset(
    {
        "ai-enterprise/CONSTITUTION.md",
        "ai-enterprise/DECISIONS.md",
        "ai-enterprise/config/risk_limits.toml",
        "ai-enterprise/config/permissions.toml",
        ".github/workflows/protected-files.yml",
        "ai-enterprise/docs/BOT.md",
    }
)
# Dessutom: agenten får aldrig ändra CI, konfiguration eller sig själv och sina egna tester.
FORBIDDEN_PREFIXES = (
    ".github/",
    "ai-enterprise/config/",
    "ai-enterprise/src/aie/dev_agent/",
    "ai-enterprise/tests/unit/test_dev_agent.py",
)
ALLOWED_ROOT = "ai-enterprise/"

_FILE = re.compile(r"^(?:---|\+\+\+) (?:[ab]/)?(\S+)")
_IMPORT = re.compile(
    r"^\s*(?:import\s+([A-Za-z_][\w.]*)|from\s+([A-Za-z_][\w.]*)\s+import\b)"
)
_STDLIB = frozenset(sys.stdlib_module_names) | {"__future__", "aie"}


@dataclass(frozen=True, slots=True)
class PatchCheck:
    ok: bool
    files: tuple[str, ...]
    changed_lines: int
    problems: tuple[str, ...]
    touches_protected: bool


def check_patch(diff: str) -> PatchCheck:
    problems: list[str] = []
    files: list[str] = []
    changed = 0
    current = ""
    if not diff.strip():
        return PatchCheck(False, (), 0, ("svaret innehöll ingen diff",), False)
    if "GIT binary patch" in diff or "Binary files" in diff:
        problems.append("binära patchar tas inte emot")
    for line in diff.splitlines():
        m = _FILE.match(line)
        if m:
            path = m.group(1)
            if path == "/dev/null":
                if line.startswith("+++"):
                    problems.append("diffen tar bort en fil")
                continue
            current = path
            if path not in files:
                files.append(path)
            continue
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            changed += 1
            body = line[1:]
            if line.startswith("+"):
                im = _IMPORT.match(body)
                if im:
                    top = (im.group(1) or im.group(2)).split(".")[0]
                    if top not in _STDLIB:
                        problems.append(
                            f"ny import utanför standardbiblioteket: {top} ({current})"
                        )
            elif "/tests/" in f"/{current}" and re.search(
                r"\bdef test_|\bassert", body
            ):
                problems.append(
                    f"diffen tar bort ett test eller en kontroll i {current}"
                )
    protected = False
    for path in files:
        if (
            path.startswith("/")
            or ".." in path.split("/")
            or not path.startswith(ALLOWED_ROOT)
        ):
            problems.append(f"ogiltig sökväg {path!r}: bara filer under {ALLOWED_ROOT}")
        if path in PROTECTED_FILES:
            protected = True
            problems.append(f"skyddad fil: {path} (kräver founder-approved)")
        elif path.startswith(FORBIDDEN_PREFIXES):
            problems.append(f"agenten får inte ändra {path}")
    if not files:
        problems.append("diffen nämner inga filer")
    if changed > MAX_CHANGED_LINES:
        problems.append(f"diffen ändrar {changed} rader; högst {MAX_CHANGED_LINES}")
    return PatchCheck(
        not problems, tuple(files), changed, tuple(dict.fromkeys(problems)), protected
    )
