"""Tester för utvecklaragenten (src/aie/dev_agent, D-050). Verifierar DR-12, DR-13, SR-01, SR-10 och SR-12.

Inget nätverk: modellen är en fejkad Groq-transport, GitHub är en fejkad transport, och agenten arbetar
i ett tillfälligt git-repo. Testsviten som agenten kör är en fejk som läser filen den ändrar.
"""

import json
import os
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
    extract_diff,
    write_report,
)
from aie.dev_agent import agent as agent_module
from aie.dev_agent.github import GitHub, GitHubError
from aie.llm import (
    LLMGateway,
    OpenAICompatibleProvider,
    ProviderRouter,
    QuotaLedger,
    RuleProvider,
    Slot,
)
from aie.llm.providers import KINDS
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = (ROOT / "docs" / "QUESTIONS-FOR-FOUNDERS.md").read_text(encoding="utf-8")


def diff_for(path, old, new):
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    {old}\n+    {new}\n"


GOOD = diff_for("ai-enterprise/src/calc.py", "return a - b", "return a + b")
BAD = diff_for("ai-enterprise/src/calc.py", "return a - b", "return a * b")


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
        )

    def calc(self):
        return (self.project / "src" / "calc.py").read_text(encoding="utf-8")

    def actions(self):
        return [e.action for e in self.audit.entries()]


class TestRun_(DevCase):
    def test_good_patch_is_applied_after_green_tests(self):
        """Verifies D-050: en diff från en gratismodell appliceras bara när hela sviten är grön; allt revideras."""
        model = FakeModel(f"Här är ändringen:\n```diff\n{GOOD}```")
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
        self.assertEqual(state["failures"], {"BL-001": 1, "BL-002": 1, "BL-003": 1})

    def test_three_failures_become_a_founder_question_and_the_item_is_skipped(self):
        """Verifies D-050: en uppgift som misslyckats tre gånger blir en grundarfråga och provas inte igen."""
        for _ in range(3):
            self.agent(FakeModel(BAD)).run()
        questions = (self.project / "docs" / "QUESTIONS-FOR-FOUNDERS.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            questions.count("### Q-BOT-001 Utvecklaragenten behöver hjälp: BL-001"), 1
        )
        self.assertIn("dev.question", self.actions())
        result = self.agent(FakeModel(GOOD)).run()
        self.assertEqual((result.success, result.attempts), (False, []))
        self.assertIn("ingen uppgift", result.stopped)

    def test_protected_file_is_refused_and_asked_about(self):
        """Verifies D-050: en diff mot en skyddad fil avvisas och blir en fråga till grundarna."""
        evil = diff_for(
            "ai-enterprise/config/risk_limits.toml", "return a - b", "return a + b"
        )
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

    def test_extract_diff(self):
        self.assertEqual(extract_diff(f"Svar:\n```diff\n{GOOD}```\nKlart."), GOOD)
        self.assertEqual(extract_diff("ingen diff här"), "")


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
