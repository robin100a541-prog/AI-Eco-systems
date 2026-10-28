"""Tester för src/aie/llm (Fas 2). Verifierar DR-01, DR-12, DR-13, ER-02 och SR-10.

Inga nätverksanrop: alla externa leverantörer får en falsk transport.
"""
import json
import tempfile
import unittest
from pathlib import Path

from aie.audit import AuditLog
from aie.config import ConfigError
from aie.llm import (
    ChatRequest,
    DataClass,
    Message,
    NoProviderAvailable,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderRouter,
    QuotaLedger,
    RuleProvider,
    Slot,
    load_providers,
)
from aie.llm.providers import USER_AGENT, _error_code
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
KEY = "gsk-THIS-MUST-NOT-LEAK"
D = DataClass


def ask(text="Vilken färg har himlen?", data_class=D.PUBLIC):
    return ChatRequest((Message("user", text),), data_class)


class FakeTransport:
    """Spelar in anrop och svarar som en OpenAI-kompatibel server, eller fallerar på begäran."""

    def __init__(self, answer="Blå", tokens=10, fail=None, status=None):
        self.calls = []
        self.answer, self.tokens, self.fail, self.status = answer, tokens, fail, status

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, json.loads(body), dict(headers)))
        if self.fail:
            raise ProviderError(self.fail, self.status)
        return json.dumps({
            "choices": [{"message": {"content": self.answer}}],
            "usage": {"total_tokens": self.tokens},
        }).encode()


class RouterCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.open_db()
        self.today = "2026-10-23"
        self.quotas = QuotaLedger(self.db, day=lambda: self.today)
        self.audit = AuditLog(self.db)

    def open_db(self):
        db = Database.open(self.dir / "data", "sim")
        self.addCleanup(db.close)
        return db

    def groq(self, transport, calls=100, tokens=10_000):
        return Slot(OpenAICompatibleProvider("groq", "groq", "openai/gpt-oss-20b", KEY, transport), calls, tokens)

    def ollama(self, transport, calls=100):
        return Slot(OpenAICompatibleProvider("ollama", "ollama", "llama3.2", None, transport), calls, 10**9)

    def rule(self):
        return Slot(RuleProvider(), 10**6, 10**9)

    def router(self, *slots):
        return ProviderRouter(slots, self.quotas, self.audit)


class TestRouting(RouterCase):
    def test_public_goes_to_first_provider_and_is_logged_without_prompt(self):
        """Verifies DR-12: första leverantören svarar; anropet loggas med tokens och kostnad 0 men utan prompt."""
        groq = FakeTransport()
        response = self.router(self.groq(groq), self.rule()).complete(ask("hemlig plan"), caller="res-1")
        self.assertEqual((response.provider, response.text, response.tokens), ("groq", "Blå", 10))
        (entry,) = self.audit.entries()
        self.assertEqual(entry.action, "llm.call")
        self.assertEqual((entry.details["provider"], entry.details["cost_minor"]), ("groq", 0))
        self.assertNotIn("hemlig plan", json.dumps(entry.details, ensure_ascii=False))

    def test_internal_data_never_leaves_the_machine(self):
        """Verifies DR-13: intern, personlig och hemlig data går aldrig till externa leverantörer."""
        for data_class in (D.INTERNAL, D.PERSONAL, D.SECRET):
            with self.subTest(data_class=data_class):
                groq, ollama = FakeTransport(), FakeTransport(answer="lokalt")
                response = self.router(self.groq(groq), self.ollama(ollama)).complete(ask(data_class=data_class), "cfo-1")
                self.assertEqual(response.provider, "ollama")
                self.assertEqual(groq.calls, [])

    def test_quota_exhausted_moves_to_next(self):
        """Verifies DR-12: när dagens kvot är slut går anropet vidare till nästa leverantör."""
        groq = FakeTransport()
        router = self.router(self.groq(groq, calls=2), self.rule())
        providers = [router.complete(ask(), "res-1").provider for _ in range(3)]
        self.assertEqual(providers, ["groq", "groq", "rule"])
        self.assertEqual(len(groq.calls), 2)

    def test_token_quota_counts(self):
        """Verifies DR-12: även tokenkvoten räknas, inte bara antalet anrop."""
        router = self.router(self.groq(FakeTransport(tokens=600), tokens=1_000), self.rule())
        self.assertEqual([router.complete(ask(), "x").provider for _ in range(3)], ["groq", "groq", "rule"])
        self.assertEqual(self.quotas.usage("groq"), (2, 1_200))

    def test_quota_survives_restart_and_resets_next_day(self):
        """Verifies DR-12 och FR-03: förbrukningen sparas i databasen och nollställs nästa UTC-dygn."""
        self.router(self.groq(FakeTransport(), calls=1), self.rule()).complete(ask(), "x")
        db = self.open_db()
        quotas = QuotaLedger(db, day=lambda: self.today)
        router = ProviderRouter((self.groq(FakeTransport(), calls=1), self.rule()), quotas)
        self.assertEqual(router.complete(ask(), "x").provider, "rule")
        self.today = "2026-10-24"
        self.assertEqual(router.complete(ask(), "x").provider, "groq")

    def test_failure_falls_back_once_and_counts(self):
        """Verifies DR-12 (§41): en leverantör som fallerar provas inte igen i samma anrop, men räknas."""
        groq = FakeTransport(fail="HTTP 503")
        response = self.router(self.groq(groq), self.rule()).complete(ask(), "x")
        self.assertEqual(response.provider, "rule")
        self.assertEqual(len(groq.calls), 1)
        self.assertEqual(self.quotas.usage("groq"), (1, 0))

    def test_all_exhausted_means_queue_never_pay(self):
        """Verifies DR-01 och DR-12: när allt är slut kastas NoProviderAvailable; inget betalt alternativ finns."""
        router = self.router(self.groq(FakeTransport(fail="HTTP 429")))
        with self.assertRaises(NoProviderAvailable) as ctx:
            router.complete(ask(), "res-1")
        self.assertIn("HTTP 429", str(ctx.exception))
        self.assertEqual(list(self.audit.entries())[-1].action, "llm.unavailable")

    def test_unexpected_response_is_provider_error(self):
        """Verifies DR-12: ett trasigt svar behandlas som ett fel och nästa leverantör tar över."""
        class Broken(FakeTransport):
            def __call__(self, *args):
                super().__call__(*args)
                return b"<html>"
        self.assertEqual(self.router(self.groq(Broken()), self.rule()).complete(ask(), "x").provider, "rule")


class TestProviders(RouterCase):
    def test_request_format_and_auth(self):
        """Verifies DR-12: OpenAI-kompatibelt anrop; nyckeln skickas som Bearer bara till externa leverantörer."""
        groq, ollama = FakeTransport(), FakeTransport()
        self.groq(groq).provider.complete(ask("hej"))
        self.ollama(ollama).provider.complete(ask("hej", D.SECRET))
        url, body, headers = groq.calls[0]
        self.assertEqual(url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(body["messages"], [{"role": "user", "content": "hej"}])
        self.assertEqual(headers["Authorization"], f"Bearer {KEY}")
        self.assertEqual(ollama.calls[0][0], "http://localhost:11434/v1/chat/completions")
        self.assertNotIn("Authorization", ollama.calls[0][2])

    def test_user_agent_and_reasoning_effort(self):
        """Verifies DR-12: egen User-Agent (urllibs standard spärras av Groq) och låg resonemangsnivå för gpt-oss."""
        groq = FakeTransport()
        self.groq(groq).provider.complete(ask("hej"))
        _url, body, headers = groq.calls[0]
        self.assertEqual(headers["User-Agent"], USER_AGENT)
        self.assertEqual(body["reasoning_effort"], "low")

    def test_failed_call_is_audited_even_when_a_fallback_answers(self):
        """Verifies DR-12, SR-10: Groqs HTTP-status loggas fast regelreserven svarar; nyckeln syns aldrig."""
        groq = FakeTransport(fail=f"HTTP 403 {KEY}", status=403)
        response = self.router(self.groq(groq), self.rule()).complete(ask(), "x")
        self.assertEqual(response.provider, "rule")
        failed = [e.details for e in self.audit.entries() if e.action == "llm.provider_failed"]
        self.assertEqual([(d["provider"], d["status"]) for d in failed], [("groq", 403)])
        self.assertNotIn(KEY, json.dumps(failed))

    def test_rate_limit_falls_back_to_the_next_groq_model(self):
        """Verifies DR-12: gränserna gäller per modell; vid 429 provas nästa Groq-modell direkt."""
        limited = FakeTransport(fail="HTTP 429 (rate_limit_exceeded)", status=429)
        second = FakeTransport(answer="ok")
        slots = (
            self.groq(limited),
            Slot(OpenAICompatibleProvider("groq-2", "groq", "openai/gpt-oss-120b", KEY, second), 100, 10_000),
            self.rule(),
        )
        response = self.router(*slots).complete(ask(), "x")
        self.assertEqual((response.provider, len(limited.calls)), ("groq-2", 1))
        failed = [e.details for e in self.audit.entries() if e.action == "llm.provider_failed"]
        self.assertEqual([(d["provider"], d["status"]) for d in failed], [("groq", 429)])

    def test_error_code_is_only_a_short_token(self):
        """Verifies SR-10: bara leverantörens felkod läses ur svarskroppen, aldrig fritext."""
        self.assertEqual(_error_code(b'{"error": {"message": "nyckel gsk_x", "code": "model_not_found"}}'),
                         "model_not_found")
        self.assertEqual(_error_code(b'{"error": {"code": "har mellanslag gsk_x"}}'), "")
        self.assertEqual(_error_code(b"<html>"), "")

    def test_key_never_leaks(self):
        """Verifies SR-10: nyckeln syns varken i felmeddelanden, repr eller audit-loggen."""
        provider = self.groq(FakeTransport(fail=f"server ekade {KEY}")).provider
        with self.assertRaises(ProviderError) as ctx:
            provider.complete(ask())
        self.assertNotIn(KEY, str(ctx.exception))
        self.assertNotIn(KEY, repr(provider))
        self.router(self.groq(FakeTransport()), self.rule()).complete(ask(), "x")
        self.assertNotIn(KEY, json.dumps([e.details for e in self.audit.entries()]))

    def test_openrouter_must_be_free(self):
        """Verifies DR-01: en OpenRouter-modell utan ':free' går inte att skapa."""
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider("or", "openrouter", "openai/gpt-4o", "k", FakeTransport())

    def test_external_provider_requires_key(self):
        """Verifies SR-10: en extern leverantör utan nyckel går inte att skapa."""
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider("groq", "groq", "m", None, FakeTransport())


class TestConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, text):
        (self.dir / "providers.toml").write_text(text, encoding="utf-8")
        return self.dir

    def test_default_config_without_keys_skips_external(self):
        """Verifies DR-12: utan nycklar i miljön hoppas groq och openrouter över; ollama och rule finns kvar."""
        slots, skipped = load_providers(ROOT / "config", environ={}, transport=FakeTransport())
        self.assertEqual([s.provider.name for s in slots], ["ollama", "rule"])
        self.assertEqual(len(skipped), 4)
        self.assertIn("GROQ_API_KEY är inte satt", skipped[0])

    def test_default_config_with_keys_keeps_order(self):
        """Verifies DR-12 (D-008): ordningen är Groqs modeller, openrouter, ollama, rule."""
        env = {"GROQ_API_KEY": "a", "OPENROUTER_API_KEY": "b"}
        slots, skipped = load_providers(ROOT / "config", environ=env, transport=FakeTransport())
        self.assertEqual([s.provider.name for s in slots], ["groq", "groq-2", "groq-3", "openrouter", "ollama", "rule"])
        self.assertEqual(skipped, ())

    def test_invalid_config_collects_all_errors(self):
        """Verifies DR-01, ER-02 och SR-10: betald typ, icke-gratis modell, saknad gräns och nyckel i filen avvisas."""
        self.write("""
config_version = 1
[[providers]]
name = "claude"
kind = "anthropic"
model = "x"
daily_calls = 1
daily_tokens = 1
[[providers]]
name = "or"
kind = "openrouter"
model = "openai/gpt-4o"
daily_calls = 1
daily_tokens = 1
[[providers]]
name = "groq"
kind = "groq"
model = "m"
daily_tokens = 1
api_key = "nej"
""")
        with self.assertRaises(ConfigError) as ctx:
            load_providers(self.dir, environ={})
        joined = "\n".join(ctx.exception.errors)
        for fragment in ("spärrade enligt D-009", "måste sluta på ':free'", "daily_calls måste vara",
                         "api_key ser ut som en hemlighet"):
            self.assertIn(fragment, joined)

    def test_missing_file(self):
        """Verifies ER-02: utan providers.toml finns inga leverantörer, och det är ett fel."""
        with self.assertRaises(ConfigError):
            load_providers(self.dir, environ={})


if __name__ == "__main__":
    unittest.main()
