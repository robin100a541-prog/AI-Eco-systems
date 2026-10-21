"""Tester för scripts/llm_smoke_test.py mot en lokal falsk server (inget nätverk).
Verifierar DR-01 (ingen tyst betalning), DR-12 (gratis modellgränssnitt) och SR-10 (nyckel läcker inte)."""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import llm_smoke_test as st  # noqa: E402

SECRET = "gsk_TEST_SECRET_SHOULD_NOT_LEAK"


class FakeLLM(BaseHTTPRequestHandler):
    mode = "ok"
    last_auth = None

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLLM.last_auth = self.headers.get("Authorization")
        if FakeLLM.mode == "429":
            self.send_response(429)
            self.end_headers()
            self.wfile.write(f"rate limited for key {SECRET}".encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("x-ratelimit-remaining-requests", "999")
        self.end_headers()
        payload = {"choices": [{"message": {"content": " Blå "}}], "usage": {"total_tokens": 12}, "model": body["model"]}
        if FakeLLM.mode == "garbage":
            payload = {"nope": True}
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *a):
        pass


class TestSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeLLM)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/v1"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeLLM.mode = "ok"

    def test_groq_happy_path_reports_answer_and_quota(self):
        """Verifies DR-12."""
        r = st.run("groq", None, environ={"GROQ_API_KEY": SECRET}, base_url=self.url)
        self.assertEqual(r["answer"], "Blå")
        self.assertEqual(r["model"], "openai/gpt-oss-20b")
        self.assertEqual(r["quota_headers"].get("x-ratelimit-remaining-requests"), "999")
        self.assertEqual(FakeLLM.last_auth, f"Bearer {SECRET}")
        self.assertNotIn(SECRET, json.dumps(r))

    def test_ollama_needs_no_key(self):
        r = st.run("ollama", "valfri-modell", environ={}, base_url=self.url)
        self.assertEqual(r["answer"], "Blå")
        self.assertIsNone(FakeLLM.last_auth)

    def test_missing_key_fails_before_network(self):
        with self.assertRaisesRegex(st.SmokeError, "GROQ_API_KEY"):
            st.run("groq", None, environ={}, base_url=self.url)

    def test_openrouter_refuses_non_free_model(self):
        """Verifies DR-01: ingen tyst betalning."""
        with self.assertRaisesRegex(st.SmokeError, ":free"):
            st.run("openrouter", "some/paid-model", environ={"OPENROUTER_API_KEY": "x"}, base_url=self.url)

    def test_openrouter_requires_model(self):
        with self.assertRaisesRegex(st.SmokeError, "--model"):
            st.run("openrouter", None, environ={"OPENROUTER_API_KEY": "x"}, base_url=self.url)

    def test_http_error_redacts_key(self):
        """Verifies SR-10."""
        FakeLLM.mode = "429"
        with self.assertRaises(st.SmokeError) as ctx:
            st.run("groq", None, environ={"GROQ_API_KEY": SECRET}, base_url=self.url)
        self.assertIn("429", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_unexpected_format_is_error(self):
        FakeLLM.mode = "garbage"
        with self.assertRaisesRegex(st.SmokeError, "Oväntat"):
            st.run("ollama", "m", environ={}, base_url=self.url)

    def test_unreachable_server_is_clean_error(self):
        with self.assertRaisesRegex(st.SmokeError, "Kunde inte nå"):
            st.run("ollama", "m", environ={}, base_url="http://127.0.0.1:9/v1", timeout=2)


if __name__ == "__main__":
    unittest.main()
