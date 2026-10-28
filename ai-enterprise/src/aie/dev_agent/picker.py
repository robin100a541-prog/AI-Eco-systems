"""Väljer små uppgifter åt utvecklaragenten (D-050). Kandidaterna hämtas ur:

1. öppna punkter i `docs/BOT-BACKLOG.md` som nämner minst en fil i repot,
2. tester som fallerar i grundkörningen,
3. `ruff`-varningar (om ruff finns),
4. krav-ID:n i `REQUIREMENTS.md` som inget test nämner men som någon källfil nämner.

De sorteras lättast först (`ease`): dokumentation och lint, sedan små tester, sist buggar.
En uppgift som redan misslyckats `MAX_FAILURES` gånger (enligt tillståndsfilen) eller redan är en
fråga i `docs/QUESTIONS-FOR-FOUNDERS.md` hoppas över.
Kontexten till modellen begränsas till `MAX_CONTEXT_CHARS` tecken (Groqs gratisgräns per minut är
liten). Av Markdown-filer skickas bara raderna som nämner uppgiftens krav-ID:n. Ett befintligt test
skickas med som exempel på importer och stil (`example_test`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_FAILURES = 3
MAX_CONTEXT_CHARS = 6_000
RETRY_CONTEXT_CHARS = 3_000  # återkopplingsanropet skickar mindre kontext
EXAMPLE_CHARS = 1_500
_REQ_ID = re.compile(r"\b(?:FR|SR|ER|DR)-\d+\b")
_BACKLOG_ITEM = re.compile(r"^- \[ \] (BL-\d+) (.*?)— öppen\s*$")
_PATH = re.compile(r"`([\w./-]+\.(?:py|md|toml))`")
_FAILED_TEST = re.compile(
    r"^(?:FAIL|ERROR): (test_\w+) \((?:tests\.)?([\w.]+)\.(\w+)\.test_\w+\)", re.MULTILINE
)
_REQ_ROW = re.compile(r"^\| ((?:FR|SR|ER|DR)-\d+) \| (.*?) \|", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Item:
    key: str  # stabil nyckel, t.ex. "BL-004" eller "ruff:I001:src/aie/x.py"
    kind: str  # backlog, failing_test, ruff, requirement
    task: str  # vad modellen ska göra
    files: tuple[str, ...]  # sökvägar relativa till ai-enterprise/


def _existing(root: Path, paths) -> tuple[str, ...]:
    out = []
    for p in paths:
        p = p.removeprefix("ai-enterprise/")
        if (root / p).is_file() and p not in out:
            out.append(p)
    return tuple(out[:3])


def backlog_items(root: Path) -> list[Item]:
    path = root / "docs" / "BOT-BACKLOG.md"
    if not path.is_file():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _BACKLOG_ITEM.match(line)
        if m:
            files = _existing(root, _PATH.findall(m.group(2)))
            if files:
                items.append(Item(m.group(1), "backlog", m.group(2).strip(), files))
    return items


def failing_test_items(root: Path, test_output: str) -> list[Item]:
    items = []
    for test, module, cls in _FAILED_TEST.findall(test_output):
        rel = "tests/" + module.replace(".", "/") + ".py"
        if (root / rel).is_file():
            items.append(
                Item(
                    f"test:{module}.{cls}.{test}",
                    "failing_test",
                    f"Testet {cls}.{test} fallerar. Hitta orsaken och rätta koden (inte testet). "
                    f"Utdata:\n{test_output[-3000:]}",
                    (rel,),
                )
            )
    return items


def ruff_items(root: Path) -> list[Item]:
    dirs = [d for d in ("src", "tests") if (root / d).is_dir()]
    if not shutil.which("ruff") or not dirs:
        return []
    run = subprocess.run(
        ["ruff", "check", "--output-format=json", *dirs],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    try:
        findings = json.loads(run.stdout or "[]")
    except ValueError:
        return []
    items = []
    for f in findings:
        rel = str(Path(f["filename"]).resolve().relative_to(root.resolve()))
        if not (root / rel).is_file():
            continue  # t.ex. E902: en katalog som saknas, ingen riktig varning
        row = f.get("location", {}).get("row", 0)
        items.append(
            Item(
                f"ruff:{f['code']}:{rel}:{row}",
                "ruff",
                f"Rätta ruff-varningen {f['code']} på rad {row} i {rel}: {f['message']}. "
                "Ändra inget beteende.",
                (rel,),
            )
        )
    return items


def requirement_items(root: Path) -> list[Item]:
    req = root / "REQUIREMENTS.md"
    if not req.is_file():
        return []
    tests = "\n".join(
        p.read_text(encoding="utf-8") for p in (root / "tests").rglob("*.py")
    )
    src = {p: p.read_text(encoding="utf-8") for p in (root / "src").rglob("*.py")}
    items = []
    for rid, text in _REQ_ROW.findall(req.read_text(encoding="utf-8")):
        if re.search(rf"\b{rid}\b", tests):
            continue
        mentions = [
            str(p.relative_to(root))
            for p, body in src.items()
            if re.search(rf"\b{rid}\b", body)
        ]
        if mentions:
            items.append(
                Item(
                    f"req:{rid}",
                    "requirement",
                    f"Kravet {rid} ({text.strip()}) har inget test. Skriv ett nytt test i en ny fil "
                    f"tests/unit/test_req_{rid.lower().replace('-', '_')}.py märkt 'Verifies {rid}'.",
                    tuple(mentions[:2]),
                )
            )
    return items


_BACKLOG_PRIORITY = re.compile(r"^\((\d)\b")
# Lättast först: dokumentation och lint, sedan små tester, sist buggar och resten (D-050).
_EASE = {"5": 0, "4": 1, "2": 2, "3": 3, "1": 4, "6": 5}


def ease(item: Item) -> int:
    if item.kind == "failing_test":
        return -1  # en röd grundkörning lagas alltid först
    if item.kind == "ruff":
        return 1
    if item.kind == "requirement":
        return 2
    m = _BACKLOG_PRIORITY.match(item.task)
    return _EASE.get(m.group(1), 3) if m else 3


def escalated(root: Path) -> set[str]:
    """Uppgifter som redan är frågor till grundarna (`**Uppgift:** <nyckel>`); de provas inte igen."""
    path = root / "docs" / "QUESTIONS-FOR-FOUNDERS.md"
    if not path.is_file():
        return set()
    return set(re.findall(r"\*\*Uppgift:\*\* (\S+)", path.read_text(encoding="utf-8")))


def pick(root: Path, test_output: str, failures: dict[str, int]) -> list[Item]:
    """Alla kandidater, lättast först, utan de som misslyckats för många gånger eller redan är frågor."""
    candidates = (
        backlog_items(root)
        + failing_test_items(root, test_output)
        + ruff_items(root)
        + requirement_items(root)
    )
    skip = escalated(root)
    keep = [i for i in candidates if failures.get(i.key, 0) < MAX_FAILURES and i.key not in skip]
    return sorted(keep, key=ease)  # stabil: samma lätthet behåller ordningen ovan


def _relevant(rel: str, body: str, task: str) -> str:
    """Av en Markdown-fil bara rubrikraden i tabeller och raderna med uppgiftens krav-ID:n."""
    ids = set(_REQ_ID.findall(task))
    if not rel.endswith(".md") or not ids:
        return body
    lines = body.splitlines()
    keep = [ln for ln in lines if set(_REQ_ID.findall(ln)) & ids]
    header = next((ln for ln in lines if ln.startswith("| ID")), "")
    return "\n".join(([header] if header and keep else []) + keep) or body


def example_test(root: Path, item: Item) -> str:
    """Början av ett befintligt test, helst ett som importerar samma modul som uppgiften rör."""
    tests = sorted((root / "tests" / "unit").glob("test_*.py"))
    modules = [
        "aie." + Path(f).with_suffix("").as_posix().removeprefix("src/aie/").replace("/", ".")
        for f in item.files
        if f.startswith("src/aie/")
    ]
    chosen = next(
        (t for t in tests for m in modules if f"from {m} import" in t.read_text(encoding="utf-8")),
        None,
    )
    if chosen is None:
        chosen = next((t for t in tests if t.stat().st_size > 2_000), tests[0] if tests else None)
    if chosen is None:
        return ""
    body = chosen.read_text(encoding="utf-8")[:EXAMPLE_CHARS]
    rel = chosen.relative_to(root).as_posix()
    return f"### Exempel på ett befintligt test: ai-enterprise/{rel} (början)\n```python\n{body}\n```\n"


def context(root: Path, item: Item, limit: int = MAX_CONTEXT_CHARS) -> str:
    parts, used = [], 0
    for rel in item.files:
        body = _relevant(rel, (root / rel).read_text(encoding="utf-8"), item.task)
        chunk = f"### Fil: ai-enterprise/{rel}\n```\n{body}\n```\n"
        if used + len(chunk) > limit:
            chunk = (
                chunk[: max(0, limit - used)] + "\n[... avkortad]\n```\n"
            )
        parts.append(chunk)
        used += len(chunk)
        if used >= limit:
            break
    return "".join(parts)
