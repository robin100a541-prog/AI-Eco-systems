"""Sök/ersätt-block från en språkmodell (D-050), samma idé som verktyget aider bygger på.

Svaga modeller skriver sällan giltiga unified diffs, men klarar att kopiera de exakta raderna som
ska ändras. Modellen svarar med ett eller flera block:

    FILE: ai-enterprise/src/aie/exempel.py
    <<<<<<< SEARCH
    (exakta befintliga rader)
    =======
    (raderna som ersätter dem)
    >>>>>>> REPLACE

En ny fil är ett block med tom SEARCH, och den får bara skapas under `ai-enterprise/tests/`.
`apply_edits` räknar fram filernas nya innehåll i minnet, kontrollerar att varje SEARCH finns
exakt en gång och bygger en unified diff, så att `patch.check_patch` granskar ändringen precis som
förut. Först när allt är godkänt skrivs filerna; `revert` lägger tillbaka dem.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

_BLOCK = re.compile(
    r"^FILE:[ \t]*`?([^\s`]+)`?[ \t]*\n+"
    r"<<<<<<< SEARCH[ \t]*\n(.*?)^=======[ \t]*\n(.*?)^>>>>>>> REPLACE[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
ROOT = "ai-enterprise/"
NEW_FILES_UNDER = "ai-enterprise/tests/"


@dataclass(frozen=True, slots=True)
class Edit:
    path: str  # relativ till repots rot, börjar med ai-enterprise/
    search: str
    replace: str


@dataclass
class Applied:
    """Resultatet av `apply_edits`: diffen för granskningen och originalen för `revert`."""

    diff: str
    files: tuple[str, ...]
    originals: dict[str, str | None]  # None = filen fanns inte innan
    contents: dict[str, str]  # filernas nya innehåll


class EditError(ValueError):
    """Blocken gick inte att applicera. Meddelandet är exakt och skickas tillbaka till modellen."""


def parse_edits(text: str) -> list[Edit]:
    edits = []
    for path, search, replace in _BLOCK.findall(text):
        path = path.strip().removeprefix("./")
        if not path.startswith(ROOT):
            path = ROOT + path
        edits.append(Edit(path, search, replace))
    return edits


def apply_edits(repo: Path, edits: list[Edit]) -> Applied:
    """Räknar fram nytt innehåll och diff, utan att skriva något. Kastar EditError vid fel."""
    if not edits:
        raise EditError(
            "svaret innehöll inga block; använd FILE: <sökväg> följt av "
            "<<<<<<< SEARCH / ======= / >>>>>>> REPLACE"
        )
    originals: dict[str, str | None] = {}
    current: dict[str, str] = {}
    for edit in edits:
        if ".." in edit.path.split("/"):
            raise EditError(f"ogiltig sökväg {edit.path!r}")
        target = repo / edit.path
        if edit.path not in originals:
            originals[edit.path] = (
                target.read_text(encoding="utf-8") if target.is_file() else None
            )
            current[edit.path] = originals[edit.path] or ""
        exists = originals[edit.path] is not None
        if not edit.search.strip():
            if exists or current.get(edit.path):
                raise EditError(
                    f"{edit.path} finns redan; en tom SEARCH skapar bara nya filer. "
                    "Kopiera de exakta raderna som ska ändras till SEARCH."
                )
            if not edit.path.startswith(NEW_FILES_UNDER):
                raise EditError(
                    f"{edit.path} finns inte. Nya filer får bara skapas under {NEW_FILES_UNDER}; "
                    "ändra en befintlig fil ur fillistan i stället."
                )
            current[edit.path] = edit.replace
            continue
        if not exists:
            raise EditError(
                f"{edit.path} finns inte. Använd bara sökvägar ur fillistan."
            )
        hits = current[edit.path].count(edit.search)
        if hits != 1:
            first = edit.search.strip().splitlines()[0][:80]
            raise EditError(
                f"SEARCH-texten finns {hits} gånger i {edit.path} (måste finnas exakt en gång). "
                f"Första raden var: {first!r}. Kopiera raderna exakt, med indrag, och ta med "
                "fler rader om texten förekommer flera gånger."
            )
        current[edit.path] = current[edit.path].replace(edit.search, edit.replace, 1)
    diff = "".join(
        _unified(path, originals[path], current[path])
        for path in originals
        if current[path] != (originals[path] or "")
    )
    if not diff:
        raise EditError("blocken ändrar ingenting (SEARCH och REPLACE är lika)")
    return Applied(diff, tuple(originals), originals, current)


def write(repo: Path, applied: Applied) -> None:
    for path, text in applied.contents.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def revert(repo: Path, applied: Applied) -> None:
    for path, original in applied.originals.items():
        target = repo / path
        if original is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(original, encoding="utf-8")


def _unified(path: str, old: str | None, new: str) -> str:
    lines = difflib.unified_diff(
        (old or "").splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="/dev/null" if old is None else f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def source_files(project: Path) -> list[str]:
    """De riktiga filerna under src/aie/ (utan __pycache__), så att modellen inte hittar på sökvägar."""
    root = project / "src" / "aie"
    return sorted(
        p.relative_to(project).as_posix()
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    )
