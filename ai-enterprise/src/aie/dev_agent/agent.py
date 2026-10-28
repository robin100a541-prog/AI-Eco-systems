"""Utvecklaragenten (D-050): en körning förbättrar koden i ett litet, testat steg.

En körning:
1. Kör hela testsviten en gång (grundkörning). Fallerande tester blir kandidater.
2. Väljer kandidater (`picker.pick`) och provar högst `MAX_ATTEMPTS` av dem, en i taget:
   skickar koden till en gratismodell via `LLMGateway`, granskar diffen (`patch.check_patch`),
   applicerar den med `git apply` och kör hela sviten.
   Avvisad diff eller rött ⇒ diffen backas (`git apply -R`) och modellen får ett nytt försök med
   exakt felet som återkoppling. Misslyckas även det noteras försöket och nästa kandidat provas.
3. Första gröna försöket blir körningens ändring. Sedan stannar körningen.
4. Är alla modeller slut (`NoProviderAvailable`), eller svarar bara regelreserven `rule`, stannar
   körningen lugnt: det räknas inte som ett misslyckat försök. Berodde det på 429 (gratisgränsen per
   minut) väntar körningen först ut minuten en gång och frågar igen.
5. `TokenPacer` sprider anropen så att körningen håller sig under `TOKENS_PER_MINUTE`.

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
import time
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

FEEDBACK_RETRIES = 1  # ett nytt försök med felet som återkoppling
MAX_TOKENS = 2_500  # svarets längd; prompt + svar ska rymmas i Groqs gratisgräns per minut
TOKENS_PER_MINUTE = 6_000  # körningens egen gräns, under Groqs gratisgräns per modell
RATE_LIMIT_WAIT = 60.0  # vid 429 på alla modeller: vänta ut minuten en gång och fråga igen
SYSTEM_PROMPT = """Du är utvecklaragenten i Python-projektet ai-enterprise. Gör EN liten ändring som löser uppgiften.

Projektet:
- Paketet heter `aie` och ligger i `ai-enterprise/src/aie/`. Importera alltid som `from aie.x import Y`
  (aldrig `ai_enterprise`, `src.aie` eller relativa importer i tester).
- Tester ligger i `ai-enterprise/tests/unit/test_*.py`, använder `unittest` och körs med
  `PYTHONPATH=src python -m unittest discover -s tests` från `ai-enterprise/`. Följ stilen i exemplet.
- Ett test som verifierar ett krav har en docstring som börjar med `Verifies <ID>`.
- Bara Python-standardbiblioteket och `aie`. Inga nya beroenden. Inga nätverksanrop.

Svaret:
- ENBART en giltig unified diff i git-format, inget annat (ingen förklaring).
- Sökvägar relativa till repots rot: `--- a/ai-enterprise/...` och `+++ b/ai-enterprise/...`.
  En ny fil har `--- /dev/null` och `+++ b/ai-enterprise/...`.
- Varje hunk-huvud `@@ -a,b +c,d @@` ska stämma exakt med raderna; sammanhangsrader ska vara
  oförändrade kopior av filen.
- Högst 200 ändrade rader. Ta aldrig bort eller försvaga tester. Rör inte `config/`, `.github/`
  eller skyddade filer."""
FEEDBACK_PROMPT = (
    "Din diff gick inte igenom ({outcome}). Exakt fel:\n{detail}\n\n"
    "Rätta felet och svara med en ny, komplett unified diff och inget annat."
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


class TokenPacer:
    """Sprider anropen så att en körning håller sig under `budget` tokens per rullande minut."""

    def __init__(
        self,
        budget: int = TOKENS_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.budget, self._clock, self._sleep = budget, clock, sleep
        self._spent: list[tuple[float, int]] = []

    def wait(self, estimate: int) -> float:
        """Väntar tills `estimate` tokens ryms i minuten. Returnerar hur länge den väntade."""
        waited = 0.0
        while True:
            now = self._clock()
            self._spent = [(t, n) for t, n in self._spent if now - t < 60]
            if not self._spent or sum(n for _, n in self._spent) + estimate <= self.budget:
                return waited
            pause = 60 - (now - self._spent[0][0]) + 0.5
            self._sleep(pause)
            waited += pause

    def record(self, tokens: int) -> None:
        self._spent.append((self._clock(), max(0, tokens)))


def estimate_tokens(messages, max_tokens: int) -> int:
    """Grov uppskattning: ungefär 3 tecken per token för kod, plus svarets längd."""
    return sum(len(m.content) for m in messages) // 3 + max_tokens


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
        pacer: TokenPacer | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.project = Path(project)
        self.repo = self.project.parent
        self.agent_id = agent_id
        self._gateway = gateway
        self._engine = engine
        self._audit = audit
        self._run_tests = run_tests
        self._clock = clock
        self._last_run: TestRun | None = None
        self._pacer = pacer or TokenPacer()
        self._sleep = sleep
        self._waited_for_rate_limit = False
        self._mark = 0

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
        messages = [
            Message("system", SYSTEM_PROMPT),
            Message(
                "user",
                f"Uppgift: {item.task}\n\n{picker.context(self.project, item)}\n"
                f"{picker.example_test(self.project, item)}",
            ),
        ]
        for round_no in range(1 + FEEDBACK_RETRIES):
            response = self._ask(messages, item, result, state)
            if response is None:
                return
            diff = extract_diff(response.text)
            outcome, detail, check = self._try_patch(diff)
            if outcome == "applied":
                self._applied(item, result, state, check, response.provider, round_no)
                return
            if round_no < FEEDBACK_RETRIES:
                # Ett nytt försök med exakt felet som återkoppling (D-050). Mindre kontext än första
                # gången, så att anropet ryms i gratisgränsen per minut.
                self._log(
                    "dev.retry_with_feedback",
                    {"item": item.key, "outcome": outcome, "detail": detail[:300]},
                )
                messages = [
                    Message("system", SYSTEM_PROMPT),
                    Message(
                        "user",
                        f"Uppgift: {item.task}\n\n"
                        f"{picker.context(self.project, item, picker.RETRY_CONTEXT_CHARS)}",
                    ),
                    Message("assistant", (diff or response.text)[:3000]),
                    Message(
                        "user", FEEDBACK_PROMPT.format(outcome=outcome, detail=detail[:1500])
                    ),
                ]
                continue
            prefix = "efter återkoppling: " if round_no else ""
            self._fail(item, result, state, outcome, prefix + detail)
            if check is not None and check.touches_protected:
                self._question(
                    result,
                    item,
                    "Modellen ville ändra en skyddad fil: " + ", ".join(check.files),
                )

    def _ask(self, messages: list[Message], item, result: RunResult, state) -> object | None:
        """Frågar modellen. None betyder att försöket redan är avslutat (stopp eller fel)."""
        request = ChatRequest(tuple(messages), DataClass.PUBLIC, max_tokens=MAX_TOKENS)
        estimate = estimate_tokens(messages, MAX_TOKENS)
        try:
            response = self._call(request, estimate)
            if self._needs_rate_limit_wait(response):
                response = self._wait_and_call_again(request, estimate)
        except SecretInPrompt:
            self._fail(
                item,
                result,
                state,
                "no_diff",
                "koden ser ut att innehålla en hemlighet; skickas inte",
            )
            return None
        if response is None:
            result.stopped = (
                "alla gratismodeller är slut (kvot eller fel); körningen stannar"
            )
            self._log("dev.quota_exhausted", {"item": item.key})
            return None
        if response.provider == "rule":
            result.stopped = (
                "bara regelreserven svarade; ingen riktig modell finns just nu"
            )
            self._log("dev.quota_exhausted", {"item": item.key, "provider": "rule"})
            return None
        return response

    def _call(self, request: ChatRequest, estimate: int):
        """Ett anrop via LLMGateway i takt med `TokenPacer`. None om alla modeller är slut."""
        self._pacer.wait(estimate)
        self._mark = sum(1 for _ in self._audit.entries())
        try:
            response = self._gateway.complete(self.agent_id, request)
        except NoProviderAvailable:
            self._pacer.record(estimate)
            return None
        self._pacer.record(response.tokens or estimate)
        return response

    def _needs_rate_limit_wait(self, response) -> bool:
        """Svarade ingen riktig modell för att alla gav 429? Då väntar körningen ut minuten en gång."""
        if self._waited_for_rate_limit or (response is not None and response.provider != "rule"):
            return False
        return any(
            e.action == "llm.provider_failed" and e.details.get("status") == 429
            for e in list(self._audit.entries())[self._mark :]
        )

    def _wait_and_call_again(self, request: ChatRequest, estimate: int):
        self._waited_for_rate_limit = True
        self._log("dev.rate_limit_wait", {"seconds": RATE_LIMIT_WAIT})
        self._sleep(RATE_LIMIT_WAIT)
        return self._call(request, estimate)

    def _try_patch(self, diff: str):
        """Granskar, applicerar och testar en diff. Returnerar (utfall, felet, granskningen)."""
        check = check_patch(diff)
        if not check.ok:
            outcome = "no_diff" if not diff.strip() else "rejected"
            return outcome, "; ".join(check.problems), check
        applied, detail = self._git_apply(diff)
        if not applied:
            return "apply_failed", detail, check
        run = self._run_tests(self.project)
        if not run.ok:
            self._git_apply(diff, reverse=True)
            return "tests_failed", run.output[-1500:], check
        self._last_run = run
        return "applied", "", check

    def _applied(self, item, result: RunResult, state, check, provider: str, round_no: int) -> None:
        run = self._last_run
        result.success, result.item, result.tests_ran = True, item, run.ran
        result.changed_files = check.files
        note = ", efter återkoppling" if round_no else ""
        result.attempts.append(
            Attempt(item.key, "applied", f"{check.changed_lines} rader, {provider}{note}")
        )
        state.pop(item.key, None)
        self._log(
            "dev.patch_applied",
            {
                "item": item.key,
                "files": list(check.files),
                "lines": check.changed_lines,
                "provider": provider,
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
