"""Tester för utvecklaragenten (src/aie/dev_agent, D-050). Verifierar DR-12, DR-13, SR-01, SR-10 och SR-12.

Inget nätverk: modellen är en fejkad Groq-transport, GitHub är en fejkad transport, och agenten arbetar
i ett tillfälligt git-repo. Testsviten som agenten kör är en fejk som läser filen den ändrar.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, load_permissions
from aie.dev_agent import (
    DevAgent,
    TestRun,
    check_patch,
    cli,
    edits,
    picker,
    write_report,
)
from aie.dev_agent import agent as agent_module
from aie.dev_agent.agent import RunResult, TokenPacer
from aie.dev_agent.github import GitHub, GitHubError
from aie.llm import (
    LLMGateway,
    OpenAICompatibleProvider,
    ProviderRouter,
    QuotaLedger,
    RuleProvider,
    Slot,
)
from aie.llm.providers import KINDS, ProviderError
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = (ROOT / "docs" / "QUESTIONS-FOR-FOUNDERS.md").read_text(encoding="utf-8")


def block(path, search, replace):
    return f"FILE: {path}\n<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n"


GOOD = block("ai-enterprise/src/calc.py", "    return a - b\n", "    return a + b\n")
BAD = block("ai-enterprise/src/calc.py", "    return a - b\n", "    return a * b\n")


class FakeModel:
    """En OpenAI-kompatibel transport som svarar med en diff per anrop."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, body, headers, timeout):
        self.calls.append(json.loads(body))
        text = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return json.dumps(
            {"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 9}}
        ).encode()


def fake_tests(project):
    """Rött bara om en ändring förstör add() (multiplicerar)."""
    body = (project / "src" / "calc.py").read_text(encoding="utf-8")
    ok = "return a * b" not in body
    return TestRun(ok, "Ran 5 tests\n" + ("OK" if ok else "FAILED (failures=1)"), 5)


class DevCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.project = self.repo / "ai-enterprise"
        (self.project / "src").mkdir(parents=True)
        (self.project / "docs").mkdir()
        (self.project / "src" / "calc.py").write_text(
            "def add(a, b):\n    return a - b\n", encoding="utf-8"
        )
        (self.project / "docs" / "QUESTIONS-FOR-FOUNDERS.md").write_text(
            QUESTIONS, encoding="utf-8"
        )
        self.backlog(["BL-001 (1 buggar) Rätta `src/calc.py` så att add adderar"])
        for cmd in (
            ["init", "-q"],
            ["add", "."],
            ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
        ):
            subprocess.run(
                ["git", *cmd], cwd=self.repo, check=True, capture_output=True
            )
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        permissions = load_permissions(ROOT / "config")
        registry = AgentRegistry(permissions, self.db)
        for agent_id, role, manager in (
            ("dev-ceo", "ceo", None),
            ("dev-1", "developer", "dev-ceo"),
        ):
            registry.register(agent_id, role, manager, "robin", "test")
            for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                registry.transition(agent_id, state, "robin", "test")
        self.engine = AuthorizationEngine(permissions, registry, "sim", self.audit)

    def backlog(self, items):
        lines = ["# Backlogg", "", "## Öppna", ""] + [
            f"- [ ] {i} — öppen" for i in items
        ]
        (self.project / "docs" / "BOT-BACKLOG.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def agent(self, model=None, calls=100, rule=True, run_tests=fake_tests):
        slots = []
        if model is not None:
            slots.append(
                Slot(
                    OpenAICompatibleProvider(
                        "groq", "groq", "m", "gsk-test-key", model
                    ),
                    calls,
                    10**6,
                )
            )
        if rule:
            slots.append(Slot(RuleProvider(), 100, 10**6))
        router = ProviderRouter(tuple(slots), QuotaLedger(self.db), self.audit)
        return DevAgent(
            self.project,
            "dev-1",
            LLMGateway(router, self.engine, self.audit),
            self.engine,
            self.audit,
            run_tests=run_tests,
            pacer=TokenPacer(budget=10**9),  # ingen takt i testerna; TestRateLimits testar den
        )

    def calc(self):
        return (self.project / "src" / "calc.py").read_text(encoding="utf-8")

    def actions(self):
        return [e.action for e in self.audit.entries()]


class TestRun_(DevCase):
    def test_good_patch_is_applied_after_green_tests(self):
        """Verifies D-050: en diff från en gratismodell appliceras bara när hela sviten är grön; allt revideras."""
        model = FakeModel(f"Här är ändringen:\n{GOOD}")
        result = self.agent(model).run()
        self.assertTrue(result.success)
        self.assertIn("return a + b", self.calc())
        self.assertEqual(result.changed_files, ("ai-enterprise/src/calc.py",))
        self.assertEqual(model.calls[0]["messages"][0]["role"], "system")
        self.assertIn("src/calc.py", model.calls[0]["messages"][1]["content"])
        for action in (
            "dev.run_started",
            "dev.item_picked",
            "llm.call",
            "dev.patch_applied",
            "dev.run_finished",
        ):
            self.assertIn(action, self.actions())
        report = write_report(self.project, result, self.actions()).read_text(
            encoding="utf-8"
        )
        self.assertIn("BL-001", report)
        self.assertIn("Ran 5 tests", report)

    def test_red_tests_discard_the_patch_and_count_the_attempt(self):
        """Verifies D-050: rött ⇒ diffen backas, försöket noteras, nästa uppgift provas; högst 3 försök."""
        self.backlog([f"BL-00{i} uppgift {i} i `src/calc.py`" for i in range(1, 5)])
        result = self.agent(FakeModel(BAD)).run()
        self.assertFalse(result.success)
        self.assertEqual(len(result.attempts), 3)
        self.assertEqual({a.outcome for a in result.attempts}, {"tests_failed"})
        self.assertIn("return a - b", self.calc())  # oförändrad
        state = json.loads(
            (self.project / "docs/bot-reports/dev-agent-state.json").read_text()
        )
        # Uppgifter som redan är frågor i repots frågefil hoppas över (picker.escalated).
        skipped = picker.escalated(self.project)
        expected = [k for k in ("BL-001", "BL-002", "BL-003", "BL-004") if k not in skipped][:3]
        self.assertEqual(state["failures"], dict.fromkeys(expected, 1))

    def test_three_failures_become_a_founder_question_and_the_item_is_skipped(self):
        """Verifies D-050: en uppgift som misslyckats tre gånger blir en grundarfråga och provas inte igen."""
        for _ in range(3):
            self.agent(FakeModel(BAD)).run()
        questions = (self.project / "docs" / "QUESTIONS-FOR-FOUNDERS.md").read_text(
            encoding="utf-8"
        )
        # Nästa lediga nummer efter frågorna som redan finns i repots frågefil.
        taken = [int(n) for n in re.findall(r"Q-BOT-(\d+)", QUESTIONS)]
        qid = f"Q-BOT-{max(taken, default=0) + 1:03d}"
        self.assertEqual(
            questions.count(f"### {qid} Utvecklaragenten behöver hjälp: BL-001"), 1
        )
        self.assertIn("dev.question", self.actions())
        result = self.agent(FakeModel(GOOD)).run()
        self.assertEqual((result.success, result.attempts), (False, []))
        self.assertIn("ingen uppgift", result.stopped)

    def test_protected_file_is_refused_and_asked_about(self):
        """Verifies D-050: en ändring av en skyddad fil avvisas och blir en fråga till grundarna."""
        (self.project / "config").mkdir()
        (self.project / "config" / "risk_limits.toml").write_text("max = 1\n", encoding="utf-8")
        evil = block("ai-enterprise/config/risk_limits.toml", "max = 1\n", "max = 100\n")
        result = self.agent(FakeModel(evil)).run()
        self.assertEqual(result.attempts[0].outcome, "rejected")
        self.assertIn("skyddad fil", result.attempts[0].detail)
        self.assertEqual(len(result.questions), 1)

    def test_quota_exhausted_or_only_rule_stops_cleanly(self):
        """Verifies DR-12: när gratiskvoten är slut stannar körningen lugnt och utan att räkna ett misslyckande."""
        for kwargs in (
            {"model": FakeModel(GOOD), "calls": 0, "rule": False},
            {"model": None, "rule": True},
        ):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                result = self.agent(**kwargs).run()
                self.assertFalse(result.success)
                self.assertEqual(result.attempts, [])
                self.assertTrue(result.stopped)
        self.assertIn("dev.quota_exhausted", self.actions())

    def test_refuses_to_run_with_an_anthropic_key(self):
        """Verifies D-050: agenten använder aldrig Anthropic; med ANTHROPIC_API_KEY satt körs den inte."""
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}):
            result = self.agent(FakeModel(GOOD)).run()
        self.assertFalse(result.success)
        self.assertIn("Anthropic", result.stopped)
        self.assertNotIn("anthropic", KINDS)
        for path in (ROOT / "src" / "aie" / "dev_agent").glob("*.py"):
            self.assertNotIn("api.anthropic.com", path.read_text(encoding="utf-8"))

    def test_role_without_tool_cannot_run(self):
        """Verifies SR-01: bara rollen developer har dev.propose_patch."""
        agent = self.agent(FakeModel(GOOD))
        agent.agent_id = "dev-ceo"
        result = agent.run()
        self.assertIn("dev.propose_patch", result.stopped)

    def test_test_suite_runs_without_secrets_in_env(self):
        """Verifies SR-10: den modellskrivna koden testas utan nycklar i miljön."""
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs["env"])
            return subprocess.CompletedProcess(args, 0, "Ran 1 test\n\nOK\n", "")

        with (
            mock.patch.dict(
                os.environ, {"GROQ_API_KEY": "gsk-x", "BOT_TOKEN": "ghp-x"}
            ),
            mock.patch.object(agent_module.subprocess, "run", fake_run),
        ):
            run = agent_module.run_test_suite(self.project)
        self.assertTrue(run.ok)
        self.assertNotIn("GROQ_API_KEY", captured)
        self.assertNotIn("BOT_TOKEN", captured)


class TestPatchCheck(unittest.TestCase):
    def test_rules(self):
        """Verifies D-050: skyddade filer, CI, egen kod, storlek, importer och försvagade tester avvisas."""
        ok = "--- a/ai-enterprise/src/x.py\n+++ b/ai-enterprise/src/x.py\n@@ -1 +1,3 @@\n+import json\n+from . import y\n-a = 1\n"
        self.assertTrue(check_patch(ok).ok, check_patch(ok).problems)
        cases = {
            "skyddad fil": ok.replace("src/x.py", "DECISIONS.md"),
            "får inte ändra": ok.replace(
                "ai-enterprise/src/x.py", ".github/workflows/x.yml"
            ),
            "dev_agent": ok.replace("src/x.py", "src/aie/dev_agent/patch.py"),
            "ogiltig sökväg": ok.replace("ai-enterprise/src/x.py", "README.md"),
            "utanför standardbiblioteket": ok.replace("import json", "import requests"),
            "högst 200": ok + "".join(f"+x{i} = {i}\n" for i in range(201)),
            "tar bort ett test": ok.replace("src/x.py", "tests/unit/test_x.py").replace(
                "-a = 1", "-        self.assertTrue(x)"
            ),
            "tar bort en fil": "--- a/ai-enterprise/src/x.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-a = 1\n",
            "ingen diff": "",
        }
        for expected, diff in cases.items():
            with self.subTest(expected=expected):
                check = check_patch(diff)
                self.assertFalse(check.ok)
                self.assertTrue(
                    any(expected in p for p in check.problems), check.problems
                )


class TestFeedback(DevCase):
    def test_failed_diff_is_retried_once_with_the_exact_error(self):
        """Verifies D-050: rött eller avvisat ⇒ ett nytt försök där modellen får exakt felet tillbaka."""
        model = FakeModel(BAD, GOOD)
        result = self.agent(model).run()
        self.assertTrue(result.success)
        self.assertEqual(len(result.attempts), 1)
        self.assertIn("efter återkoppling", result.attempts[0].detail)
        retry = model.calls[1]["messages"]
        self.assertEqual([m["role"] for m in retry], ["system", "user", "assistant", "user"])
        self.assertIn("return a * b", retry[2]["content"])
        self.assertIn("tests_failed", retry[3]["content"])
        self.assertIn("FAILED (failures=1)", retry[3]["content"])
        self.assertIn("dev.retry_with_feedback", self.actions())

    def test_search_must_match_exactly_once_and_the_error_is_fed_back(self):
        """Verifies D-050: en SEARCH som inte finns exakt en gång avvisas, och felet går tillbaka till modellen."""
        missing = block("ai-enterprise/src/calc.py", "    return a / b\n", "    return a + b\n")
        model = FakeModel(missing, GOOD)
        result = self.agent(model).run()
        self.assertTrue(result.success)
        feedback = model.calls[1]["messages"][3]["content"]
        self.assertIn("apply_failed", feedback)
        self.assertIn("finns 0 gånger i ai-enterprise/src/calc.py", feedback)

    def test_invented_files_are_rejected_but_new_tests_are_allowed(self):
        """Verifies D-050: en påhittad fil avvisas; en ny testfil under tests/ får skapas."""
        repo = self.repo
        invented = edits.parse_edits(block("ai-enterprise/src/aie/finance.py", "x = 1\n", "x = 2\n"))
        with self.assertRaisesRegex(edits.EditError, "finns inte"):
            edits.apply_edits(repo, invented)
        new_src = edits.parse_edits(block("ai-enterprise/src/aie/finance.py", "", "x = 2\n"))
        with self.assertRaisesRegex(edits.EditError, "bara skapas under ai-enterprise/tests/"):
            edits.apply_edits(repo, new_src)
        new_test = edits.parse_edits(block("tests/unit/test_new.py", "", "import unittest\n"))
        applied = edits.apply_edits(repo, new_test)
        self.assertIn("+++ b/ai-enterprise/tests/unit/test_new.py", applied.diff)
        self.assertIn("--- /dev/null", applied.diff)
        edits.write(repo, applied)
        self.assertTrue((self.project / "tests/unit/test_new.py").is_file())
        edits.revert(repo, applied)
        self.assertFalse((self.project / "tests/unit/test_new.py").exists())

    def test_red_tests_restore_the_original_file(self):
        """Verifies D-050: rött efter skrivning ⇒ filen återställs exakt."""
        before = self.calc()
        self.agent(FakeModel(BAD)).run()
        self.assertEqual(self.calc(), before)

    def test_rejected_import_is_fed_back_and_counted_once(self):
        """Verifies D-050: en otillåten import avvisas, återkopplas en gång, och räknas sedan som ett försök."""
        bad_import = block("ai-enterprise/tests/unit/test_x.py", "", "import ai_enterprise\n")
        model = FakeModel(bad_import)
        self.backlog(["BL-001 uppgift i `src/calc.py`"])
        result = self.agent(model).run()
        self.assertEqual(len(model.calls), 2)
        self.assertIn("ai_enterprise", model.calls[1]["messages"][3]["content"])
        self.assertEqual([a.outcome for a in result.attempts], ["rejected"])

    def test_prompt_names_the_package_the_block_format_and_the_real_files(self):
        """Verifies D-050: prompten anger paketet `aie`, sök/ersätt-formatet och de riktiga filerna."""
        self.assertIn("from aie.x import Y", agent_module.SYSTEM_PROMPT)
        self.assertIn("ai_enterprise", agent_module.SYSTEM_PROMPT)  # uttryckligen förbjudet
        self.assertIn("<<<<<<< SEARCH", agent_module.SYSTEM_PROMPT)
        self.assertIn("standardbiblioteket", agent_module.SYSTEM_PROMPT)
        (self.project / "src" / "aie").mkdir(parents=True)
        (self.project / "src" / "aie" / "ledger.py").write_text("X = 1\n", encoding="utf-8")
        model = FakeModel(GOOD)
        self.agent(model).run()
        self.assertIn("\nsrc/aie/ledger.py\n", model.calls[0]["messages"][1]["content"])
        self.assertIn("Fillista", model.calls[0]["messages"][1]["content"])


class TestPicker(unittest.TestCase):
    def test_easiest_first_and_escalated_items_are_skipped(self):
        """Verifies D-050: dokumentation och lint före tester och buggar; frågor till grundarna hoppas över."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            (root / "docs" / "BOT-BACKLOG.md").write_text(
                "- [ ] BL-001 (1 buggar) i `a.py` — öppen\n"
                "- [ ] BL-002 (2 kravtäckning) i `a.py` — öppen\n"
                "- [ ] BL-004 (4 kodkvalitet) i `a.py` — öppen\n"
                "- [ ] BL-005 (5 dokumentation) i `a.py` — öppen\n",
                encoding="utf-8",
            )
            (root / "docs" / "QUESTIONS-FOR-FOUNDERS.md").write_text(
                "### Q-BOT-001\n- **Uppgift:** BL-002\n", encoding="utf-8"
            )
            keys = [i.key for i in picker.pick(root, "", {})]
        self.assertEqual(keys, ["BL-005", "BL-004", "BL-001"])


class TestRateLimits(DevCase):
    def test_all_models_rate_limited_waits_a_minute_once_and_asks_again(self):
        """Verifies D-050: ger alla Groq-modeller 429 väntar körningen ut minuten en gång och frågar igen."""
        calls = []

        def limited_once(url, body, headers, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise ProviderError("HTTP 429 (rate_limit_exceeded)", 429, "rate_limit_exceeded")
            return FakeModel(GOOD)(url, body, headers, timeout)

        waits = []
        agent = self.agent(limited_once)
        agent._sleep = waits.append
        result = agent.run()
        self.assertTrue(result.success)
        self.assertEqual(waits, [agent_module.RATE_LIMIT_WAIT])
        self.assertIn("dev.rate_limit_wait", self.actions())

    def test_pacer_keeps_a_run_under_the_per_minute_budget(self):
        """Verifies D-050: anropen sprids så att en körning håller sig under sin tokengräns per minut."""
        now, slept = [0.0], []

        def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds

        pacer = TokenPacer(6000, clock=lambda: now[0], sleep=sleep)
        self.assertEqual(pacer.wait(4000), 0.0)
        pacer.record(4000)
        now[0] = 10.0
        self.assertAlmostEqual(pacer.wait(4000), 50.5)
        pacer.record(4000)
        self.assertEqual(slept, [50.5])

    def test_only_groq_models_in_groqs_current_list_are_used(self):
        """Verifies DR-12, D-050: en Groq-reservmodell används bara om Groq erbjuder den just nu."""
        env = {"GROQ_API_KEY": "gsk-test"}
        offered = frozenset({"openai/gpt-oss-20b"})  # 120b saknas just nu i den här låtsaslistan
        with tempfile.TemporaryDirectory() as tmp:
            agent, _ = cli.bootstrap(ROOT / "config", Path(tmp), env, lister=lambda kind, key: offered)
            names = [s.provider.name for s in agent._gateway._router._slots]
        self.assertEqual(names[:1], ["groq-2"])
        self.assertNotIn("groq", names)

        def broken(kind, key):
            raise ProviderError("groq: modellistan gav HTTP 503", 503)

        with tempfile.TemporaryDirectory() as tmp:
            agent, _ = cli.bootstrap(ROOT / "config", Path(tmp), env, lister=broken)
            names = [s.provider.name for s in agent._gateway._router._slots]
        self.assertEqual(names[:2], ["groq", "groq-2"])


class TestContext(unittest.TestCase):
    def test_example_test_matches_the_module_and_shows_imports(self):
        """Verifies D-050: ett befintligt test som importerar samma modul skickas med som exempel."""
        item = picker.Item("x", "backlog", "t", ("src/aie/audit/log.py",))
        example = picker.example_test(ROOT, item)
        self.assertIn("tests/unit/test_audit.py", example)
        self.assertIn("from aie.audit", example)
        self.assertLessEqual(len(example), picker.EXAMPLE_CHARS + 200)

    def test_markdown_context_keeps_only_the_requirement_rows(self):
        """Verifies D-050: av REQUIREMENTS.md skickas bara raderna med uppgiftens krav-ID:n."""
        item = picker.Item("BL-002", "backlog", "ER-12 och SR-15 saknar test", ("REQUIREMENTS.md",))
        text = picker.context(ROOT, item)
        self.assertIn("| ER-12 |", text)
        self.assertIn("| SR-15 |", text)
        self.assertNotIn("| SR-01 |", text)
        self.assertLess(len(text), 1500)


class TestReportsWithoutPR(unittest.TestCase):
    def test_report_only_run_opens_no_pr_and_rides_with_the_next_change(self):
        """Verifies D-050: en körning utan ändring öppnar ingen PR; rapporten följer med nästa ändring."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            project = repo / "ai-enterprise"
            (project / "docs" / "bot-reports").mkdir(parents=True)
            (project / "README.md").write_text("x\n", encoding="utf-8")
            for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t",
                                                        "commit", "-qm", "init"]):
                subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
            summary, out = Path(tmp) / "summary.md", Path(tmp) / "out.json"
            env = {"GITHUB_STEP_SUMMARY": str(summary)}
            agent = mock.Mock()
            audit = mock.Mock()
            audit.entries.return_value = []
            cwd = os.getcwd()
            os.chdir(project)
            self.addCleanup(os.chdir, cwd)
            with mock.patch.object(cli, "bootstrap", return_value=(agent, audit)):
                agent.run.return_value = RunResult("2026-10-28T10:00:00+00:00", stopped="kvot")
                self.assertEqual(cli.run(Path("config"), "claude/dev-agent-1", out, env), 0)
                self.assertFalse(json.loads(out.read_text())["committed"])
                self.assertTrue((project / cli.PENDING_DIR / "dev-agent-2026-10-28-1000.md").is_file())
                self.assertIn("kvot", summary.read_text(encoding="utf-8"))

                (project / "README.md").write_text("y\n", encoding="utf-8")
                agent.run.return_value = RunResult(
                    "2026-10-28T13:00:00+00:00", success=True,
                    item=picker.Item("BL-001", "backlog", "t", ("README.md",)),
                    changed_files=("README.md",),
                )
                cli.run(Path("config"), "claude/dev-agent-2", out, env)
            data = json.loads(out.read_text())
            self.assertTrue(data["committed"])
            files = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=repo,
                                   capture_output=True, text=True, check=True).stdout.split()
            self.assertIn("ai-enterprise/docs/bot-reports/dev-agent-2026-10-28-1000.md", files)
            self.assertIn("ai-enterprise/docs/bot-reports/dev-agent-2026-10-28-1300.md", files)
            self.assertIn("ai-enterprise/README.md", files)
            self.assertEqual(list((project / cli.PENDING_DIR).iterdir()), [])


class TestGitHub(unittest.TestCase):
    def test_opens_pr_and_enables_auto_merge_without_leaking_the_token(self):
        """Verifies D-050, SR-10: PR öppnas med automatisk merge; token syns aldrig i fel."""
        calls = []

        def transport(method, url, headers, body):
            calls.append((method, url, json.loads(body)))
            if url.endswith("/pulls"):
                return 201, json.dumps(
                    {"number": 7, "node_id": "PR_x", "html_url": "u"}
                ).encode()
            return 200, b'{"data": {}}'

        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "r.json"
            result.write_text(
                json.dumps(
                    {
                        "committed": True,
                        "branch": "claude/dev-agent-1",
                        "title": "t",
                        "body": "b",
                    }
                )
            )
            env = {"BOT_TOKEN": "ghp-secret", "GITHUB_REPOSITORY": "o/r"}
            self.assertEqual(cli.open_pr(result, env, transport), 0)
        self.assertEqual(calls[0][2]["head"], "claude/dev-agent-1")
        self.assertIn("enablePullRequestAutoMerge", calls[1][2]["query"])
        self.assertEqual(calls[1][2]["variables"], {"id": "PR_x"})
        failing = GitHub(
            "ghp-secret", "o/r", lambda *a: (422, b'{"message": "bad ghp-secret"}')
        )
        with self.assertRaises(GitHubError) as ctx:
            failing.open_pr("b", "t", "x")
        self.assertNotIn("ghp-secret", str(ctx.exception))
        self.assertNotIn("ghp-secret", repr(failing))

    def test_auto_merge_failure_still_reports_the_pr(self):
        """Verifies D-050: går automatisk merge inte att slå på finns PR:en ändå och körningen lyckas."""

        def transport(method, url, headers, body):
            if url.endswith("/pulls"):
                return 201, b'{"number": 8, "node_id": "PR_y"}'
            return 200, b'{"errors": [{"message": "Protected branch rules not configured"}]}'

        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "r.json"
            result.write_text(json.dumps({"committed": True, "branch": "b", "title": "t", "body": "b"}))
            env = {"BOT_TOKEN": "ghp-secret", "GITHUB_REPOSITORY": "o/r"}
            self.assertEqual(cli.open_pr(result, env, transport), 0)

    def test_llm_summary_names_provider_and_first_groq_status(self):
        """Verifies D-050: körningen visar vem som svarade och första Groq-statusen, aldrig nycklar."""
        entry = mock.Mock
        entries = [
            entry(action="llm.provider_failed", details={"provider": "groq", "status": 413, "reason": "groq: HTTP 413"}),
            entry(action="llm.call", details={"provider": "rule"}),
        ]
        self.assertEqual(
            cli.llm_summary(entries), "första Groq-anropet: groq: HTTP 413; svarade: rule; fel: groq: HTTP 413"
        )
        ok = [entry(action="llm.call", details={"provider": "groq"})]
        self.assertEqual(cli.llm_summary(ok), "första Groq-anropet: HTTP 200; svarade: groq")
        self.assertEqual(cli.llm_summary([]), "första Groq-anropet: inget; svarade: ingen")

    def test_bootstrap_uses_repo_config_and_free_providers_only(self):
        """Verifies DR-12, D-050: agenten byggs från repots konfiguration; utan nycklar finns bara lokala leverantörer."""
        with tempfile.TemporaryDirectory() as tmp:
            agent, _audit = cli.bootstrap(ROOT / "config", Path(tmp), environ={})
            providers = [s.provider.name for s in agent._gateway._router._slots]
        self.assertNotIn("groq", providers)
        self.assertIn("rule", providers)
        self.assertEqual(agent.agent_id, "dev-1")


if __name__ == "__main__":
    unittest.main()
