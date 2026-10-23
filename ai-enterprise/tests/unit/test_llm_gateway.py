"""Tester för src/aie/llm/gateway.py: agenter når ProviderRouter bara via Authorization Engine.

Verifierar SR-01, SR-02 (§35–36), DR-12, DR-13 och SR-10. Alla tester körs med repots riktiga
`config/permissions.toml` och en falsk transport. Inga nätverksanrop.

Läcktesterna placerar en unik markör i prompten och kontrollerar sedan varje ställe där den
skulle kunna hamna: det som skickas till externa leverantörer, loggfilen och audit-loggen.
"""

import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.llm import (
    LLM_TOOL,
    ChatRequest,
    DataClass,
    LLMGateway,
    Message,
    NoProviderAvailable,
    OpenAICompatibleProvider,
    ProviderRouter,
    QuotaLedger,
    RuleProvider,
    SecretInPrompt,
    Slot,
)
from aie.memory import Database
from aie.monitoring import LOG_FILE_NAME, setup_logging, shutdown_logging

from .org_helpers import register_in_line

from .test_llm_router import FakeTransport

ROOT = Path(__file__).resolve().parents[2]
KEY = "gsk-GATEWAY-KEY-MUST-NOT-LEAK"
MARKER = "HEMLIG-AFFÄRSPLAN-7f3a"  # unik text som aldrig får synas utanför datorn
D = DataClass


def ask(text, data_class=D.PUBLIC):
    return ChatRequest((Message("user", text),), data_class)


class GatewayCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        setup_logging(self.dir / "logs", "DEBUG", stream=io.StringIO())
        self.addCleanup(shutdown_logging)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.permissions = load_permissions(ROOT / "config")
        self.registry = AgentRegistry(self.permissions, self.db)
        self.engine = AuthorizationEngine(
            self.permissions, self.registry, "sim", self.audit
        )
        self.external = FakeTransport(answer="svar")
        self.local = FakeTransport(answer="lokalt svar")
        groq = OpenAICompatibleProvider(
            "groq", "groq", "openai/gpt-oss-20b", KEY, self.external
        )
        ollama = OpenAICompatibleProvider(
            "ollama", "ollama", "llama3.2", None, self.local
        )
        self.router = ProviderRouter(
            (
                Slot(groq, 100, 10_000),
                Slot(ollama, 100, 10**9),
                Slot(RuleProvider(), 10**6, 10**9),
            ),
            QuotaLedger(self.db, day=lambda: "2026-10-23"),
            self.audit,
        )
        self.gateway = LLMGateway(self.router, self.engine, self.audit)
        self.make("res-1", "researcher", AgentState.ACTIVE)

    def make(self, agent_id, role, state):
        register_in_line(self.registry, self.permissions, agent_id, role, by="robin")
        path = {
            AgentState.PROPOSED: (),
            AgentState.TESTING: (AgentState.CREATED, AgentState.TESTING),
            AgentState.ACTIVE: (
                AgentState.CREATED,
                AgentState.TESTING,
                AgentState.ACTIVE,
            ),
            AgentState.SUSPENDED: (
                AgentState.CREATED,
                AgentState.TESTING,
                AgentState.ACTIVE,
                AgentState.SUSPENDED,
            ),
        }[state]
        for target in path:
            self.registry.transition(agent_id, target, "robin", "test")

    def actions(self):
        return [e.action for e in self.audit.entries()]

    def everything_written(self):
        """All text som lämnat processen eller sparats: externa anrop, loggfil och databasfiler."""
        shutdown_logging()
        sent = repr(self.external.calls)
        log_file = (self.dir / "logs" / LOG_FILE_NAME).read_text(encoding="utf-8")
        with sqlite3.connect(self.dir / "data" / "sim.db") as conn:
            audit_rows = repr(conn.execute("SELECT * FROM audit_log").fetchall())
        conn.close()
        return sent, log_file, audit_rows


class TestOnlyThroughAuthorization(GatewayCase):
    def test_allowed_agent_reaches_router_and_both_steps_are_logged(self):
        """Verifies SR-01: en agent med llm.complete når routern; både behörighet och anrop revideras."""
        response = self.gateway.complete("res-1", ask("Vilken färg har himlen?"))
        self.assertEqual((response.provider, response.text), ("groq", "svar"))
        self.assertEqual(self.actions(), ["tool.allowed", "llm.call"])
        allowed = next(self.audit.entries())
        self.assertEqual(allowed.details["tool"], LLM_TOOL)

    def test_role_without_mandate_is_denied_logged_and_nothing_sent(self):
        """Verifies SR-02 (§36): en roll utan llm.complete nekas, nekandet revideras och inget skickas."""
        restricted = load_permissions(ROOT / "config")
        mandates = dict(restricted.roles)
        researcher = mandates["researcher"]
        mandates["researcher"] = type(researcher)(
            researcher.role,
            researcher.department,
            researcher.tools - {LLM_TOOL},
            researcher.description,
        )
        engine = AuthorizationEngine(
            type(restricted)(restricted.tools, mandates),
            self.registry,
            "sim",
            self.audit,
        )
        gateway = LLMGateway(self.router, engine, self.audit)
        with self.assertRaises(PermissionDenied) as ctx:
            gateway.complete("res-1", ask("hej"))
        self.assertIn("ingår inte i mandatet", str(ctx.exception))
        self.assertEqual(self.external.calls, [])
        self.assertEqual(self.actions(), ["tool.denied"])

    def test_unknown_suspended_and_proposed_agents_denied(self):
        """Verifies SR-02, SR-14: okänd, avstängd och ännu inte skapad agent nekas och inget skickas."""
        self.make("sus-1", "researcher", AgentState.SUSPENDED)
        self.make("new-1", "researcher", AgentState.PROPOSED)
        for agent_id in ("ghost", "sus-1", "new-1"):
            with self.subTest(agent=agent_id), self.assertRaises(PermissionDenied):
                self.gateway.complete(agent_id, ask("hej"))
        self.assertEqual(self.external.calls, [])
        self.assertEqual(self.actions().count("tool.denied"), 3)
        self.assertNotIn("llm.call", self.actions())

    def test_every_role_in_repo_config_has_the_tool_in_catalog(self):
        """Verifies SR-02: llm.complete finns i katalogen och i mandatet för MVP:ns roller."""
        self.assertIn(LLM_TOOL, self.permissions.tools)
        for role, mandate in self.permissions.roles.items():
            with self.subTest(role=role):
                self.assertTrue(mandate.allows(LLM_TOOL))

    def test_quota_exhausted_means_paused_through_gateway(self):
        """Verifies DR-12: via gatewayen ger slut kvot överallt "köa arbetet", aldrig betalning."""
        router = ProviderRouter(
            (
                Slot(
                    OpenAICompatibleProvider("groq", "groq", "m", KEY, self.external),
                    0,
                    0,
                ),
            ),
            QuotaLedger(self.db, day=lambda: "2026-10-23"),
            self.audit,
        )
        with self.assertRaises(NoProviderAvailable) as ctx:
            LLMGateway(router, self.engine, self.audit).complete("res-1", ask("hej"))
        self.assertIn("köa arbetet", str(ctx.exception))
        self.assertEqual(self.external.calls, [])
        self.assertEqual(self.actions(), ["tool.allowed", "llm.unavailable"])


class TestNoLeaks(GatewayCase):
    def test_restricted_classes_never_reach_external_provider_logs_or_audit(self):
        """Verifies DR-13, SR-10: internal, personal och secret går bara lokalt och syns varken i loggfil eller audit-logg."""
        for data_class in (D.INTERNAL, D.PERSONAL, D.SECRET):
            with self.subTest(data_class=data_class.value):
                response = self.gateway.complete(
                    "res-1", ask(f"Sammanfatta {MARKER}", data_class)
                )
                self.assertEqual(
                    response.provider, "ollama"
                )  # första lokala leverantören
        sent, log_file, audit_rows = self.everything_written()
        self.assertNotIn(MARKER, sent)
        self.assertNotIn(MARKER, log_file)
        self.assertNotIn(MARKER, audit_rows)
        self.assertEqual(self.external.calls, [])

    def test_public_prompt_content_never_logged_or_audited(self):
        """Verifies SR-10: även public-text som skickas externt sparas aldrig i loggfil eller audit-logg."""
        self.gateway.complete("res-1", ask(f"Offentlig fråga {MARKER}"))
        self.assertIn(
            MARKER, repr(self.external.calls)
        )  # den fick skickas, den är public
        _, log_file, audit_rows = self.everything_written()
        self.assertNotIn(MARKER, log_file)
        self.assertNotIn(MARKER, audit_rows)

    def test_key_value_secret_in_prompt_is_refused_everywhere(self):
        """Verifies SR-10: en prompt med api_key=... avvisas helt, oavsett dataklass, och syns ingenstans."""
        secret = "sk-or-v1-HEMLIG"
        for data_class in (D.PUBLIC, D.SECRET):
            with (
                self.subTest(data_class=data_class.value),
                self.assertRaises(SecretInPrompt),
            ):
                self.gateway.complete(
                    "res-1", ask(f"använd api_key={secret} mot tjänsten", data_class)
                )
        self.assertEqual(self.external.calls, [])
        self.assertEqual(self.local.calls, [])
        self.assertEqual(self.actions().count("llm.blocked_secret"), 2)
        for written in self.everything_written():
            self.assertNotIn(secret, written)

    def test_environment_secret_value_in_prompt_is_refused(self):
        """Verifies SR-10: värdet av en hemlig miljövariabel i en prompt avvisas och skickas aldrig."""
        env_secret = "ghp_ENV-SECRET-VALUE-123"
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": env_secret}):
            with self.assertRaises(SecretInPrompt):
                self.gateway.complete("res-1", ask(f"Här är token {env_secret}"))
            for written in self.everything_written():
                self.assertNotIn(env_secret, written)
        self.assertEqual(self.external.calls, [])

    def test_provider_key_never_in_logs_or_audit(self):
        """Verifies SR-10: leverantörens API-nyckel skickas bara i Authorization-huvudet, aldrig till logg eller audit."""
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": KEY}):
            self.gateway.complete("res-1", ask("hej"))
            _, log_file, audit_rows = self.everything_written()
        self.assertNotIn(KEY, log_file)
        self.assertNotIn(KEY, audit_rows)
        self.assertEqual(self.external.calls[0][2]["Authorization"], f"Bearer {KEY}")


if __name__ == "__main__":
    unittest.main()
