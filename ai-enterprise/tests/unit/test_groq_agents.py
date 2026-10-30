"""Tester för `simulate --agents groq` (PR 8, D-060). Verifierar D-008, D-009, DR-13, SR-10 och FR-20.

Inget nätverk: Groq ersätts av en transport som svarar med de skriptade agenternas åtgärder.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from aie.config import load_config
from aie.llm import ChatRequest, DataClass, Message
from aie.memory import Database
from aie.simulation import (
    ScriptedPolicy,
    SimClock,
    Simulation,
    SimulationError,
    WorkCycle,
    build_gateway,
)
from aie.simulation.agents import agent_data_class, ensure_org
from aie.simulation.readiness import evaluate
from aie.system import build_system

from .fixture_config import TEST_CONFIG
from .test_simulation import scenario

KEY = "gsk_test_" + "x" * 40  # inte en riktig nyckel
PROVIDERS = """config_version = 1

[[providers]]
name = "groq"
kind = "groq"
model = "openai/gpt-oss-120b"
daily_calls = {calls}
daily_tokens = 180000

[[providers]]
name = "openrouter"
kind = "openrouter"
model = "openai/gpt-oss-20b:free"
daily_calls = 45
daily_tokens = 100000

[[providers]]
name = "rule"
kind = "rule"
daily_calls = 100000
daily_tokens = 100000000
"""


class FakeGroq:
    """Svarar som Groqs OpenAI-kompatibla API, med de skriptade agenternas svar."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        payload = json.loads(body)
        self.calls.append((url, payload, dict(headers)))
        request = ChatRequest(messages=tuple(Message(m["role"], m["content"]) for m in payload["messages"]),
                              data_class=DataClass.PUBLIC)
        text = ScriptedPolicy()(request)
        return json.dumps({"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 100}}).encode()


class GroqCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config_dir = self.dir / "config"
        shutil.copytree(TEST_CONFIG, self.config_dir)
        self.config = load_config(self.config_dir)
        self.groq = FakeGroq()

    def providers(self, calls):
        (self.config_dir / "providers.toml").write_text(PROVIDERS.format(calls=calls), encoding="utf-8")

    def start(self, name="normal"):
        sc = scenario(name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        clock = SimClock(sc.start_date)
        self.system = build_system(self.config, self.db, self.config_dir, clock=clock)
        ensure_org(self.system.registry, "yorgo")
        return Simulation.start(self.system, self.config, sc, "yorgo", clock)

    def gateway(self, environ=None):
        env = {"GROQ_API_KEY": KEY, "OPENROUTER_API_KEY": "sk-or-test"} if environ is None else environ
        return build_gateway(self.system, "groq", self.config_dir, environ=env, transport=self.groq)


class TestGroqAgents(GroqCase):
    def test_groq_agents_run_the_simulation_with_public_sim_data_only(self):
        """Verifies DR-13 och D-060: förfrågningarna är märkta public, innehåller bara SIM och går bara till Groq."""
        self.providers(900)
        sim = self.start()
        cycle = WorkCycle(sim, self.system, self.gateway(), agent_data_class("groq"))
        days = cycle.run(3)
        self.assertEqual((len(days), cycle.paused), (3, None))
        self.assertTrue(self.groq.calls)
        self.assertTrue(all(url.startswith("https://api.groq.com/") for url, _, _ in self.groq.calls))
        self.assertTrue(any(a["outcome"] == "done" for d in days for a in d["actions"]))
        calls = [e for e in self.system.audit.entries() if e.action == "llm.call"]
        self.assertTrue(calls)
        self.assertEqual({(e.details["provider"], e.details["data_class"], e.details["cost_minor"]) for e in calls},
                         {("groq", "public", 0)})
        self.assertFalse(any(KEY in json.dumps(e.details) for e in self.system.audit.entries()))  # SR-10
        self.assertTrue(all("SIM" in p["messages"][0]["content"] for _, p, _ in self.groq.calls))

    def test_only_groq_is_used_never_a_fallback(self):
        """Verifies D-008 och D-009: utan GROQ_API_KEY körs inget, och openrouter eller rule tar aldrig över."""
        self.providers(900)
        self.start()
        with self.assertRaisesRegex(ValueError, "GROQ_API_KEY.*docs/setup.md"):
            self.gateway(environ={"OPENROUTER_API_KEY": "sk-or-test"})
        router = self.gateway()._router
        self.assertEqual([s.provider.name for s in router._slots], ["groq"])

    def test_the_run_pauses_when_the_quota_is_used_and_resumes_later(self):
        """Verifies D-060: räcker inte kvoten till en hel dag pausas körningen före dagen; inget halvt dygn sparas."""
        self.providers(5)  # två agenter per dag: två hela dagar, sedan ett anrop kvar
        sim = self.start()
        cycle = WorkCycle(sim, self.system, self.gateway(), agent_data_class("groq"))
        days = cycle.run(10)
        self.assertEqual(len(days), 2)
        self.assertEqual(sim.last_day, 2)
        self.assertIn("kvoten", cycle.paused)
        self.assertIn("Ingen betald reserv", cycle.paused)
        self.assertEqual(len(self.groq.calls), 4)
        self.assertIn("simulation.paused_quota", [e.action for e in self.system.audit.entries()])
        self.providers(900)  # ett nytt UTC-dygn motsvaras här av en större kvot
        cycle = WorkCycle(sim, self.system, self.gateway(), agent_data_class("groq"))
        self.assertEqual(len(cycle.run(2)), 2)
        self.assertEqual(sim.last_day, 4)

    def test_public_requests_are_refused_outside_sim_and_evaluations_refuse_groq(self):
        """Verifies SR-11 och D-060: public-märkning bara i sim; bedömningar körs aldrig med groq."""
        self.providers(900)
        sim = self.start()
        sim.config = type("C", (), {"system": type("S", (), {"environment": "prod"})(),
                                    "risk": type("R", (), {"currency": "SEK"})()})()
        with self.assertRaises(SimulationError):
            WorkCycle(sim, self.system, self.gateway(), agent_data_class("groq"))
        with self.assertRaisesRegex(ValueError, "groq"):
            evaluate(self.config, self.config_dir, scenario("normal"), 1, 5, "groq")
        self.assertIs(agent_data_class("local"), DataClass.INTERNAL)
        self.assertIs(agent_data_class("scripted"), DataClass.INTERNAL)
