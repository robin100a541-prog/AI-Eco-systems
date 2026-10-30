"""Utvecklaragenten (D-050): en körning förbättrar koden i ett litet, testat steg.

En körning:
1. Kör hela testsviten en gång (grundkörning). Fallerande tester blir kandidater.
2. Väljer kandidater (`picker.pick`) och provar högst `MAX_ATTEMPTS` av dem, en i taget:
   skickar koden och fillistan till en gratismodell via `LLMGateway`, som svarar med sök/ersätt-block
   (`edits.py`). Blocken görs om till en diff som granskas (`patch.check_patch`), skrivs och
   hela sviten körs. Fel i blocken, avvisad ändring eller rött ⇒ filerna återställs och modellen
   får ett nytt försök med exakt felet. Misslyckas även det noteras försöket och nästa kandidat provas.
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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..audit import AuditLog
from ..authorization import AuthorizationEngine, PermissionDenied
from ..llm import ChatRequest, DataClass, LLMGateway, Message, NoProviderAvailable
from ..llm.gateway import SecretInPrompt
from . import backlog, picker
from . import edits as edit_blocks
from .patch import check_patch
from .verify import RunCmd, Verifier, run_cmd

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
- Använd bara filer som finns i fillistan. Hitta aldrig på moduler eller sökvägar.

Svaret är ENBART ett eller flera sök/ersätt-block, ingen förklaring:

FILE: ai-enterprise/src/aie/exempel.py
<<<<<<< SEARCH
    for r in rader:
        summa += r
=======
    for r in sorted(rader):
        summa += r
>>>>>>> REPLACE

- SEARCH är en exakt kopia av befintliga rader i filen, med samma indrag, och ska finnas exakt en
  gång. Ta med så få rader som behövs för att den blir unik.
- REPLACE är raderna som ersätter dem.
- En ny testfil under `ai-enterprise/tests/` är ett block med tom SEARCH och hela filen i REPLACE.
- Högst 200 ändrade rader. Ta aldrig bort eller försvaga tester. Rör inte `config/`, `.github/`
  eller skyddade filer."""
MAX_REWRITES = 2  # backloggpunkter utan kontroll som skrivs om per körning
SIDE_MAX_TOKENS = 800
REWRITE_PROMPT = (
    "Du sköter backloggen i Python-projektet ai-enterprise. En punkt saknar en kontroll som kan "
    "bevisa att den är klar. Svara med EN rad och inget annat: `Klart när:` följt av en eller flera "
    "kontroller inom backticks, t.ex. Klart när: `verifies ER-12`. Välj kontroller som faktiskt "
    "bevisar punktens mål."
)
REFILL_PROMPT = (
    "Du sköter backloggen i Python-projektet ai-enterprise. Föreslå högst 3 nya, små förbättringar "
    "av koden nedan. En rad per förslag, exakt i formen\n"
    "- [ ] (P kategori) Vad och var. Klart när: `kontroll`\n"
    "där P är 1 buggar, 2 kravtäckning, 3 säkerhet, 4 kodkvalitet eller 5 dokumentation. Varje förslag "
    "ska gå att göra i en liten ändring och bevisas av kontrollen. Inga nya funktioner, inget om "
    "pengar, betalningar, konton eller kunder, och inga ändringar av config/, .github/ eller skyddade "
    "filer. Svara bara med raderna."
)
FEEDBACK_PROMPT = (
    "Dina block gick inte igenom ({outcome}). Exakt fel:\n{detail}\n\n"
    "Rätta felet och svara med nya sök/ersätt-block och inget annat."
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
    backlog_added: list[str] = field(default_factory=list)  # nya punkter (BL-NNN)
    backlog_checked: list[str] = field(default_factory=list)  # punkter som fått en kontroll

    @property
    def backlog_changed(self) -> bool:
        return bool(self.backlog_added or self.backlog_checked)


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


def _file_list(project: Path) -> str:
    """De riktiga källfilerna, relativt till ai-enterprise/ (kort, så att prompten ryms i gratisgränsen)."""
    files = edit_blocks.source_files(project)
    return "### Fillista: de enda filerna under ai-enterprise/src/aie/\n" + "\n".join(files) + "\n"


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
        run: RunCmd = run_cmd,
        refill: bool = True,
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
        self._verifier = Verifier(self.project, run)
        self._refill_enabled = refill
        self._read_files: list[str] = []  # filerna modellen fick läsa; underlag för nya punkter

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
        self._make_checkable(result)
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
        if self._refill_enabled and not result.stopped.startswith(("alla gratismodeller", "bara regel")):
            self._refill(result)
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
        self._log(
            "dev.item_picked",
            {"item": item.key, "kind": item.kind, "checks": [str(c) for c in item.checks]},
        )
        self._read_files += [f for f in item.files if f not in self._read_files]
        messages = [
            Message("system", SYSTEM_PROMPT),
            Message(
                "user",
                f"Uppgift: {item.task}\n\n{picker.context(self.project, item)}\n"
                f"{picker.example_test(self.project, item)}\n{_file_list(self.project)}",
            ),
        ]
        for round_no in range(1 + FEEDBACK_RETRIES):
            response = self._ask(messages, item, result, state)
            if response is None:
                return
            outcome, detail, check = self._try_edits(response.text, item)
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
                    Message("assistant", response.text[:3000]),
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

    def _try_edits(self, text: str, item: picker.Item):
        """Applicerar blocken, granskar, testar och bevisar uppgiften. Returnerar (utfall, felet, granskningen).

        Gröna tester räcker inte: uppgiftens egen kontroll (`verify.py`) måste också gå igenom,
        annars kastas ändringen och försöket räknas som misslyckat.
        """
        blocks = edit_blocks.parse_edits(text)
        try:
            applied = edit_blocks.apply_edits(self.repo, blocks)
        except edit_blocks.EditError as exc:
            return ("no_diff" if not blocks else "apply_failed"), str(exc), None
        check = check_patch(applied.diff)
        if not check.ok:
            return "rejected", "; ".join(check.problems), check
        edit_blocks.write(self.repo, applied)
        run = self._run_tests(self.project)
        if not run.ok:
            edit_blocks.revert(self.repo, applied)
            return "tests_failed", run.output[-1500:], check
        proven, detail = self._verifier.verify(item.checks)
        if not proven:
            edit_blocks.revert(self.repo, applied)
            self._log("dev.check_failed", {"item": item.key, "detail": detail[:300]})
            return "check_failed", detail, check
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
        if item.kind == "backlog" and backlog.mark_done(
            self.project, item.key, self._clock().date().isoformat()
        ) and item.key not in result.backlog_checked:
            result.backlog_checked.append(item.key)  # backloggen ändrad: följer med i PR:en
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

    # --- Backloggen: kontroller och nya punkter --------------------------------------------------

    def _make_checkable(self, result: RunResult) -> None:
        """Skriver om backloggpunkter som saknar kontroll så att de går att bevisa (högst två per körning)."""
        for item in picker.uncheckable(self.project)[:MAX_REWRITES]:
            answer = self._ask_side(
                [
                    Message("system", REWRITE_PROMPT),
                    Message(
                        "user",
                        f"Punkt {item.key}: {item.task}\n\n{backlog.CHECK_HELP}\n\n"
                        f"{picker.context(self.project, item, picker.RETRY_CONTEXT_CHARS)}",
                    ),
                ]
            )
            if answer is None:
                return  # ingen modell just nu
            checks = backlog.clause_checks(self.project, answer)
            if checks and self._already_true(checks):
                checks = ()  # en kontroll som redan går igenom bevisar ingenting
            clause = backlog.add_check(self.project, item.key, checks)
            self._log("dev.backlog_checked", {"item": item.key, "clause": clause or ""})
            if clause:
                result.backlog_checked.append(item.key)

    def _refill(self, result: RunResult) -> None:
        """Ber modellen om högst tre nya, små punkter som går att bevisa, ur koden den läste."""
        if not self._read_files or len(backlog.open_items(self.project)) >= backlog.MAX_OPEN_ITEMS:
            return
        code = "".join(
            f"### Fil: ai-enterprise/{f}\n```\n{(self.project / f).read_text(encoding='utf-8')[:3000]}\n```\n"
            for f in self._read_files[:2]
            if (self.project / f).is_file()
        )
        answer = self._ask_side(
            [
                Message("system", REFILL_PROMPT),
                Message("user", f"{backlog.CHECK_HELP}\n\n{code}"),
            ]
        )
        if answer is None:
            return
        keep, seen = [], set()
        accepted = 0
        for proposal in backlog.parse_proposals(answer, self.project):
            if accepted >= backlog.MAX_NEW_ITEMS:
                break
            norm = proposal.text.split("Klart när:")[0].lower()
            if norm in seen or backlog.is_duplicate(self.project, proposal):
                continue
            if self._already_true(proposal.checks):
                self._log("dev.backlog_rejected", {"text": proposal.text[:120], "why": "redan uppfylld"})
                continue  # punkten vore "klar" utan någon ändring
            seen.add(norm)
            accepted += 1
            if backlog.classify(proposal) == "founders":
                item = picker.Item(f"förslag:{proposal.text[:60]}", "suggestion", proposal.text, ())
                self._question(
                    result,
                    item,
                    "Utvecklaragenten föreslår det här, men det rör skyddade filer, pengar, konton "
                    "eller något utanför CONSTITUTION.md/ROADMAP.md, så bara grundarna får avgöra det.",
                    question="Ska förslaget läggas i backloggen, ändras eller strykas?",
                )
            else:
                keep.append(proposal)
        result.backlog_added = backlog.add_items(self.project, keep)
        self._log("dev.backlog_refilled", {"added": result.backlog_added})

    def _already_true(self, checks) -> bool:
        """En ny kontroll måste gå att misslyckas med: går den redan igenom bevisar den ingenting."""
        return self._verifier.verify(tuple(checks))[0]

    def _ask_side(self, messages: list[Message]) -> str | None:
        """Ett anrop utanför en uppgift (backloggen). None om ingen riktig modell svarar."""
        request = ChatRequest(tuple(messages), DataClass.PUBLIC, max_tokens=SIDE_MAX_TOKENS)
        try:
            response = self._call(request, estimate_tokens(messages, SIDE_MAX_TOKENS))
        except SecretInPrompt:
            return None
        if response is None or response.provider == "rule":
            return None
        return response.text

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

    def _question(
        self,
        result: RunResult,
        item: picker.Item,
        why: str,
        question: str = "Hur ska uppgiften lösas, eller ska den strykas?",
    ) -> None:
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
            f"- **Uppgift:** {item.key}\n- **Fråga:** {question}\n"
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
        "",
        "## Backloggen",
        f"- Nya punkter: {', '.join(result.backlog_added) or 'inga'}",
        f"- Punkter som fått en kontroll: {', '.join(result.backlog_checked) or 'inga'}",
    ]
    lines += ["", "## Revisionslogg", ", ".join(audit_actions) or "tom", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
