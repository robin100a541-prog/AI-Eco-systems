"""Bevis på att en uppgift är klar (D-050). Gröna tester räcker inte: uppgiftens egen kontroll ska gå igenom.

En kontroll är en kort text, samma format i koden och i `docs/BOT-BACKLOG.md` (efter `Klart när:`):

    ruff <fil> [REGEL]        ruff hittar inget (av REGEL) i filen
    test <test-id>            testet går igenom, t.ex. tests.unit.test_x.Klass.test_y
    flaky-test <test-id>      testet går igenom 3 gånger i rad
    verifies <KRAV-ID>        ett test vars docstring säger "Verifies <KRAV-ID>" finns och går igenom
    grep <fil> <text>         filen innehåller texten
    !grep <fil> <text>        filen innehåller inte texten

Går en kontroll inte igenom kastas ändringen, även om hela sviten är grön.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

FLAKY_RUNS = 3
_KINDS = ("ruff", "test", "flaky-test", "verifies", "grep", "!grep")
_REQ_ID = re.compile(r"(?:FR|SR|ER|DR)-\d+")
_TEST_ID = re.compile(r"tests(?:\.\w+)+")
_RUFF_CODE = re.compile(r"[A-Z]+\d+")
_SAFE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")

# (projekt, argv) -> (returkod, utdata)
RunCmd = Callable[[Path, list[str]], tuple[int, str]]


@dataclass(frozen=True, slots=True)
class Check:
    kind: str
    arg: str

    def __str__(self) -> str:
        return f"{self.kind} {self.arg}"


def parse_check(text: str, project: Path | None = None) -> Check | None:
    """En kontroll, eller None om texten inte är en giltig kontroll (fel form eller fil som saknas)."""
    kind, _, arg = text.strip().partition(" ")
    arg = arg.strip()
    if kind not in _KINDS or not arg:
        return None
    if kind == "verifies" and not _REQ_ID.fullmatch(arg):
        return None
    if kind in ("test", "flaky-test") and not _TEST_ID.fullmatch(arg):
        return None
    if kind in ("ruff", "grep", "!grep"):
        path, _, rest = arg.partition(" ")
        if path.startswith("/") or ".." in path.split("/"):
            return None
        if kind == "ruff" and rest and not _RUFF_CODE.fullmatch(rest.strip()):
            return None
        if kind != "ruff" and not rest.strip():
            return None
        if project is not None and not (project / path).is_file():
            return None
    return Check(kind, arg)


def checks_in(text: str, project: Path | None = None) -> tuple[Check, ...]:
    """Kontrollerna i en backlogg-rad: varje `...` efter "Klart när:" som är en giltig kontroll."""
    _, found, tail = text.partition("Klart när:")
    if not found:
        return ()
    parsed = (parse_check(c, project) for c in re.findall(r"`([^`]+)`", tail))
    return tuple(c for c in parsed if c is not None)


def run_cmd(project: Path, argv: list[str]) -> tuple[int, str]:
    """Kör ett kommando utan nycklar i miljön (koden kan vara modellskriven)."""
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV}
    env["PYTHONPATH"] = str(project / "src")
    try:
        proc = subprocess.run(
            argv,
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{argv[0]}: {exc}"
    return proc.returncode, proc.stdout + proc.stderr


class Verifier:
    def __init__(self, project: Path, run: RunCmd = run_cmd) -> None:
        self.project = Path(project)
        self._run = run

    def verify(self, checks: tuple[Check, ...]) -> tuple[bool, str]:
        """Alla kontroller måste gå igenom. Utan kontroller finns inget bevis, och då räknas det som fel."""
        if not checks:
            return False, "uppgiften har ingen kontroll som kan bevisa att den är klar"
        handlers = {
            "ruff": self._ruff,
            "test": self._test,
            "flaky-test": self._flaky_test,
            "verifies": self._verifies,
            "grep": self._grep,
            "!grep": self._not_grep,
        }
        for check in checks:
            ok, detail = handlers[check.kind](check.arg)
            if not ok:
                return False, f"kontrollen `{check}` gick inte igenom: {detail}"
        return True, ""

    def _ruff(self, arg: str) -> tuple[bool, str]:
        path, _, code = arg.partition(" ")
        argv = ["ruff", "check", "--output-format=json", path]
        if code:
            argv[2:2] = ["--select", code]
        status, out = self._run(self.project, argv)
        if status == 127:
            return False, "ruff finns inte, så kontrollen kan inte bevisas"
        try:
            findings = json.loads(out or "[]")
        except ValueError:
            return False, f"ruff gav oväntad utdata: {out[:200]}"
        if findings:
            first = findings[0]
            row = first.get("location", {}).get("row", "?")
            return (
                False,
                f"ruff hittar fortfarande {len(findings)} fynd, t.ex. {first.get('code')} på rad {row}: {first.get('message')}",
            )
        return True, ""

    def _unittest(self, target: str, runs: int = 1) -> tuple[bool, str]:
        for i in range(runs):
            status, out = self._run(
                self.project, [sys.executable, "-m", "unittest", target]
            )
            ran = re.search(r"^Ran (\d+) tests?", out, re.MULTILINE)
            if status != 0 or not ran or ran.group(1) == "0":
                which = f" (körning {i + 1} av {runs})" if runs > 1 else ""
                return False, f"{target} gick inte igenom{which}: {out[-800:]}"
        return True, ""

    def _test(self, arg: str) -> tuple[bool, str]:
        return self._unittest(arg)

    def _flaky_test(self, arg: str) -> tuple[bool, str]:
        return self._unittest(arg, FLAKY_RUNS)

    def _verifies(self, rid: str) -> tuple[bool, str]:
        pattern = re.compile(rf"Verifies\b[^\n]*\b{re.escape(rid)}\b")
        modules = sorted(
            ".".join(p.relative_to(self.project).with_suffix("").parts)
            for p in (self.project / "tests").rglob("test_*.py")
            if pattern.search(p.read_text(encoding="utf-8"))
        )
        if not modules:
            return False, f"inget test har en docstring med 'Verifies {rid}'"
        for module in modules:
            ok, detail = self._unittest(module)
            if not ok:
                return False, detail
        return True, ""

    def _grep(self, arg: str) -> tuple[bool, str]:
        path, _, text = arg.partition(" ")
        target = self.project / path
        if not target.is_file():
            return False, f"{path} finns inte"
        if text not in target.read_text(encoding="utf-8"):
            return False, f"{path} innehåller inte {text!r}"
        return True, ""

    def _not_grep(self, arg: str) -> tuple[bool, str]:
        path, _, text = arg.partition(" ")
        target = self.project / path
        if target.is_file() and text in target.read_text(encoding="utf-8"):
            return False, f"{path} innehåller fortfarande {text!r}"
        return True, ""
