"""Utvecklaragenten (D-050): en körning förbättrar koden i ett litet, testat steg.

En körning:
1. Kör hela testsviten en gång (grundkörning). Fallerande tester blir kandidater.
2. Väljer kandidater (`picker.pick`) och provar högst `MAX_ATTEMPTS` av dem, en i taget:
   skickar koden till en gratismodell via `LLMGateway`, granskar diffen (`patch.check_patch`),
   applicerar den med `git apply` och kör hela sviten.
   Rött ⇒ diffen backas (`git apply -R`), försöket noteras och nästa kandidat provas.
3. Första gröna försöket blir körningens ändring. Sedan stannar körningen.
4. Är alla modeller slut (`NoProviderAvailable`), eller svarar bara regelreserven `rule`, stannar
   körningen direkt och lugnt: det räknas inte som ett misslyckat försök.

Agenten använder bara gratisleverantörerna i `providers.toml` (Groq, OpenRouter `:free`, Ollama,
`rule`), aldrig Anthropic. Den skickar bara repots kod, som är publik (D-014), som `public`-data.
Testerna körs utan miljövariabler med nycklar. Allt revideras; rapporten och tillståndet skrivs till
`docs/bot-reports/`, och uppgifter som misslyckats tre gånger blir frågor till grundarna.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..audit import AuditLog
from ..authorization import AuthorizationEngine, PermissionDenied
from ..llm import ChatRequest, DataClass, LLMGateway, Message, NoProviderAvailable
from ..llm.gateway import SecretInPrompt
from . import picker
from .patch import check_patch, extract_diff

TOOL = "dev.propose_patch"
MAX_ATTEMPTS = 3
STATE_FILE = "docs/bot-reports/dev-agent-state.json"
QUESTIONS_FILE = "docs/QUESTIONS-FOR-FOUNDERS.md"
_SAFE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")

SYSTEM_PROMPT = (
    "Du är utvecklaragenten i ett Python-projekt (bara standardbiblioteket, unittest). "
    "Gör EN liten ändring som löser uppgiften. Svara ENBART med en unified diff i git-format, "
    "med sökvägar relativa till repots rot (de börjar med ai-enterprise/), och inget annat. "
    "Högst 200 ändrade rader. Inga nya beroenden. Ta aldrig bort eller försvaga tester."
)


@dataclass(frozen=True, slots=True)
class TestRun:
    ok: bool
    output: str
    ran: int


@dataclass
class Attempt:
    item: str
    outcome: str  # applied, rejected, tests_failed, apply_failed, no_diff
    detail: str = ""


@dataclass
class RunResult:
    started_at: str
    success: bool = False
    item: picker.Item | None = None
    attempts: list[Attempt] = field(default_factory=list)
    stopped: str = ""  # varför körningen stannade i förtid, t.ex. kvoten slut
    tests_ran: int = 0
    changed_files: tuple[str, ...] = ()
    questions: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


def run_test_suite(project: Path) -> TestRun:
    """Hela sviten i en egen process, utan nycklar i miljön (koden kan vara modellskriven)."""
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV}
    env["PYTHONPATH"] = str(project / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    out = proc.stdout + proc.stderr
    ran = re.search(r"^Ran (\d+) tests?", out, re.MULTILINE)
    ok = proc.returncode == 0 and bool(re.search(r"^OK", out, re.MULTILINE))
    return TestRun(ok, out, int(ran.group(1)) if ran else 0)


class DevAgent:
    def __init__(
        self,
        project: Path,
        agent_id: str,
        gateway: LLMGateway,
        engine: AuthorizationEngine,
        audit: AuditLog,
        run_tests: Callable[[Path], TestRun] = run_test_suite,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.project = Path(project)
        self.repo = self.project.parent
        self.agent_id = agent_id
        self._gateway = gateway
        self._engine = engine
        self._audit = audit
        self._run_tests = run_tests
        self._clock = clock

    # --- Körningen -----------------------------------------------------------------------------

    def run(self) -> RunResult:
        result = RunResult(self._clock().isoformat(timespec="seconds"))
        if os.environ.get("ANTHROPIC_API_KEY"):
            result.stopped = "ANTHROPIC_API_KEY är satt; agenten använder aldrig Anthropic och körs inte"
            self._log("dev.refused", {"reason": result.stopped})
            return result
        try:
            self._engine.require(self.agent_id, TOOL)
        except PermissionDenied as exc:
            result.stopped = str(exc)
            return result
        self._log("dev.run_started", {})
        baseline = self._run_tests(self.project)
        result.tests_ran = baseline.ran
        state = self._load_state()
        candidates = picker.pick(
            self.project, "" if baseline.ok else baseline.output, state
        )
        for item in candidates:
            if len(result.attempts) >= MAX_ATTEMPTS or result.success or result.stopped:
                break
            if not baseline.ok and item.kind != "failing_test":
                continue  # med en röd grundkörning lagas först det som är trasigt
            self._attempt(item, result, state)
        if not candidates:
            result.stopped = result.stopped or "ingen uppgift att ta"
        self._save_state(state)
        self._log(
            "dev.run_finished",
            {
                "success": result.success,
                "attempts": len(result.attempts),
                "stopped": result.stopped,
            },
        )
        return result

    def _attempt(
        self, item: picker.Item, result: RunResult, state: dict[str, int]
    ) -> None:
        self._log("dev.item_picked", {"item": item.key, "kind": item.kind})
        request = ChatRequest(
            (
                Message("system", SYSTEM_PROMPT),
                Message(
                    "user",
                    f"Uppgift: {item.task}\n\n{picker.context(self.project, item)}",
                ),
            ),
            DataClass.PUBLIC,
            max_tokens=3000,  # prompt + max_tokens ska rymmas i Groqs gratisgräns per minut
        )
        try:
            response = self._gateway.complete(self.agent_id, request)
        except NoProviderAvailable:
            result.stopped = (
                "alla gratismodeller är slut (kvot eller fel); körningen stannar"
            )
            self._log("dev.quota_exhausted", {"item": item.key})
            return
        except SecretInPrompt:
            self._fail(
                item,
                result,
                state,
                "no_diff",
                "koden ser ut att innehålla en hemlighet; skickas inte",
            )
            return
        if response.provider == "rule":
            result.stopped = (
                "bara regelreserven svarade; ingen riktig modell finns just nu"
            )
            self._log("dev.quota_exhausted", {"item": item.key, "provider": "rule"})
            return
        diff = extract_diff(response.text)
        check = check_patch(diff)
        if not check.ok:
            self._fail(item, result, state, "rejected", "; ".join(check.problems))
            if check.touches_protected:
                self._question(
                    result,
                    item,
                    "Modellen ville ändra en skyddad fil: " + ", ".join(check.files),
                )
            return
        applied, detail = self._git_apply(diff)
        if not applied:
            self._fail(item, result, state, "apply_failed", detail)
            return
        run = self._run_tests(self.project)
        if not run.ok:
            self._git_apply(diff, reverse=True)
            self._fail(item, result, state, "tests_failed", run.output[-1500:])
            return
        result.success, result.item, result.tests_ran = True, item, run.ran
        result.changed_files = check.files
        result.attempts.append(
            Attempt(
                item.key, "applied", f"{check.changed_lines} rader, {response.provider}"
            )
        )
        state.pop(item.key, None)
        self._log(
            "dev.patch_applied",
            {
                "item": item.key,
                "files": list(check.files),
                "lines": check.changed_lines,
                "provider": response.provider,
                "tests": run.ran,
            },
        )

    def _fail(
        self, item, result: RunResult, state: dict[str, int], outcome: str, detail: str
    ) -> None:
        result.attempts.append(Attempt(item.key, outcome, detail))
        state[item.key] = state.get(item.key, 0) + 1
        self._log(
            "dev.attempt_failed",
            {"item": item.key, "outcome": outcome, "failures": state[item.key]},
        )
        if state[item.key] >= picker.MAX_FAILURES:
            self._question(
                result,
                item,
                f"Utvecklaragenten har misslyckats {state[item.key]} gånger med "
                f"uppgiften. Senast: {outcome}.",
            )

    # --- Git, tillstånd, frågor ------------------------------------------------------------------

    def _git_apply(self, diff: str, reverse: bool = False) -> tuple[bool, str]:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".diff", delete=False, encoding="utf-8"
        ) as f:
            f.write(diff)
        try:
            args = ["git", "apply", "--whitespace=nowarn"] + (["-R"] if reverse else [])
            check = subprocess.run(
                args + ["--check", f.name],
                cwd=self.repo,
                capture_output=True,
                text=True,
                check=False,
            )
            if check.returncode != 0:
                return False, check.stderr.strip()[:500]
            done = subprocess.run(
                args + [f.name],
                cwd=self.repo,
                capture_output=True,
                text=True,
                check=False,
            )
            return done.returncode == 0, done.stderr.strip()[:500]
        finally:
            os.unlink(f.name)

    def _load_state(self) -> dict[str, int]:
        path = self.project / STATE_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: int(v) for k, v in data.get("failures", {}).items()}

    def _save_state(self, state: dict[str, int]) -> None:
        path = self.project / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"failures": dict(sorted(state.items()))}, indent=2) + "\n",
            encoding="utf-8",
        )

    def _question(self, result: RunResult, item: picker.Item, why: str) -> None:
        path = self.project / QUESTIONS_FILE
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8")
        if f"Uppgift:** {item.key}" in text:
            return  # frågan finns redan
        numbers = [int(n) for n in re.findall(r"Q-BOT-(\d+)", text)]
        qid = f"Q-BOT-{max(numbers, default=0) + 1:03d}"
        block = (
            f"### {qid} Utvecklaragenten behöver hjälp: {item.key}\n"
            f"- **Datum:** {self._clock().date().isoformat()}\n- **Status:** Öppen\n"
            f"- **Uppgift:** {item.key}\n- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?\n"
            f"- **Varför det spelar roll:** {why}\n"
            f"- **Alternativ:**\n  1. Ge en ledtråd eller lös den själv.\n  2. Stryk uppgiften.\n"
            f"- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.\n"
            f"- **Svar (grundare, namn och datum):**\n\n"
        )
        marker = "## Öppna\n"
        if marker in text:
            text = text.replace(marker, marker + "\n" + block, 1).replace(
                "\n\n_Inga ännu._\n\n## Besvarade", "\n\n## Besvarade", 1
            )
        else:
            text += "\n" + block
        path.write_text(text, encoding="utf-8")
        result.questions.append(qid)
        self._log("dev.question", {"question": qid, "item": item.key})

    def _log(self, action: str, details: dict) -> None:
        self._audit.append(self.agent_id, action, details)


def write_report(project: Path, result: RunResult, audit_actions: list[str]) -> Path:
    stamp = result.started_at[:16].replace(":", "").replace("T", "-")
    path = project / "docs" / "bot-reports" / f"dev-agent-{stamp}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Utvecklaragenten {result.started_at}", "", "## Gjort"]
    if result.success and result.item:
        lines.append(f"- {result.item.key}: {result.item.task[:200]}")
        lines.append(f"- Ändrade filer: {', '.join(result.changed_files)}")
    else:
        lines.append("- Ingen kodändring den här körningen.")
    lines += ["", "## Försök"] + (
        [f"- {a.item}: {a.outcome} {a.detail[:200]}".rstrip() for a in result.attempts]
        or ["- Inga."]
    )
    lines += [
        "",
        "## Tester",
        f"`Ran {result.tests_ran} tests`" + (" OK" if result.success else ""),
    ]
    if result.stopped:
        lines += ["", "## Stannade", result.stopped]
    lines += [
        "",
        "## Frågor till grundarna",
        ", ".join(result.questions) or "Inga nya.",
    ]
    lines += ["", "## Revisionslogg", ", ".join(audit_actions) or "tom", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
