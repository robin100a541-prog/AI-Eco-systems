"""Opportunity Scout (Robin 2026-10-30): register, dygnscykel, förslag via CEO och gränser. Falsk modell och källor."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from aie.config import load_config
from aie.dashboard.export import build_status
from aie.governance.cli import build
from aie.llm.providers import ChatResponse
from aie.memory import Database
from aie.scout.cycle import render_register, render_weekly, run_cycle, update_questions
from aie.scout.register import RegisterError, ScoutRegister
from aie.simulation.agents import ensure_org
from aie.system import build_system

from .fixture_config import TEST_CONFIG
from .test_discovery import FakeGateway, FakeReader


class DeciderGateway(FakeGateway):
    """Som FakeGateway, men svarar även som CFO, risk och CEO."""

    def complete(self, agent, request):
        system = request.messages[0].content
        if system.startswith(("Du är CFO", "Du är Riskchef")):
            ideas = json.loads(system.split("Underlag (JSON): ", 1)[1])["ideas"]
            return ChatResponse("fake", "m", json.dumps({"assessments": [
                {"idea_id": i["id"], "position": "for", "reason": "ok"} for i in ideas]}), 0)
        if system.startswith("Du är CEO"):
            ideas = json.loads(system.split("Underlag (JSON): ", 1)[1])["ideas"]
            return ChatResponse("fake", "m", json.dumps({
                "idea_id": ideas[0]["id"], "chosen_action": "testa", "reasoning": "starkast", "evidence": ["S1"],
                "risk_class": "low", "expected_result": "hypotes", "stop_conditions": "ingen försäljning",
                "follow_up": "varje vecka"}), 0)
        return super().complete(agent, request)


class KeyReader(FakeReader):
    def __init__(self):
        super().__init__()
        self.secret_calls = []

    def fetch(self, agent, url, secret_headers=None):
        if secret_headers:
            self.secret_calls.append((url, secret_headers))
        return super().fetch(agent, url)


class ScoutCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database.open(Path(tmp.name) / "data", "sim")
        self.addCleanup(self.db.close)
        self.config = load_config(TEST_CONFIG)
        self.gov = build(self.config, self.db, TEST_CONFIG)
        ensure_org(self.gov.registry, "robin")

    def cycle(self, gateway=None, reader=None, day=date(2026, 11, 2), environ=None):
        return run_cycle(self.gov, reader or FakeReader(), gateway or DeciderGateway(), TEST_CONFIG, "robin", day,
                         environ if environ is not None else {})


class TestCycle(ScoutCase):
    def test_finds_scores_and_proposes_through_ceo_to_the_founder_queue(self):
        out = self.cycle()
        self.assertEqual(len(out["new"]), 10)
        self.assertEqual(len(out["proposed"]), 2)  # propose_max
        reg = ScoutRegister(self.db, self.gov.audit)
        proposed = [e for e in reg.current() if e.status == "proposed"]
        self.assertTrue(all(e.data["request_id"] for e in proposed))
        self.assertTrue(all(src["url"] and src["quote"] for e in proposed for src in e.data["sources"]))
        self.assertEqual(len(self.gov.queue.pending()), 2)  # bara grundarna kan godkänna
        history = reg.history(proposed[0].key)
        self.assertEqual([h.status for h in history], ["new", "scored", "proposed"])
        self.assertTrue(all(h.reason for h in history))
        text = render_register(out, date(2026, 11, 2))
        self.assertIn("proposed", text)
        self.assertIn("— https://", text)
        self.assertIn("## Topp 5", render_weekly(out, date(2026, 11, 2)))

    def test_founder_approval_moves_the_proposal_to_approved(self):
        out = self.cycle()
        reg = ScoutRegister(self.db, self.gov.audit)
        key = out["proposed"][0]
        self.gov.queue.approve("robin", reg.get(key).data["request_id"], "testa")
        out = self.cycle()
        self.assertIn(key, out["decided"])
        self.assertEqual(reg.get(key).status, "approved")

    def test_research_failure_is_reported_and_nothing_is_invented(self):
        out = self.cycle(reader=FakeReader(fail=True))
        self.assertIn("researchen gav 0", out["failed"])
        self.assertEqual(out["entries"], [])

    def test_api_keys_are_optional_and_only_sent_to_their_host(self):
        out = self.cycle(environ={})
        self.assertTrue(any("YOUTUBE_API_KEY saknas" in n for n in out["notes"]))
        reader = KeyReader()
        self.cycle(reader=reader, environ={"ETSY_API_KEY": "k" * 20})
        self.assertTrue(reader.secret_calls)
        self.assertTrue(all(u.startswith("https://openapi.etsy.com/") for u, _ in reader.secret_calls))
        self.assertNotIn("k" * 20, json.dumps([e.data for e in ScoutRegister(self.db, self.gov.audit).current()]))


class TestRegister(ScoutCase):
    def test_append_only_reasons_and_scout_cannot_approve(self):
        reg = ScoutRegister(self.db, self.gov.audit)
        reg.record("scout-1", "x", "pod", "fotboll", "Tröja", "new", {}, "ny")
        with self.assertRaises(RegisterError):
            reg.move("scout-1", "x", "approved", "försöker godkänna själv")
        with self.assertRaises(RegisterError):
            reg.move("scout-1", "x", "scored", "  ")
        with self.assertRaises(sqlite3.DatabaseError):
            with self.db.transaction() as tx:
                tx.execute("UPDATE scout_entries SET status = 'approved'")

    def test_stale_ideas_are_stopped_with_a_reason(self):
        self.cycle(day=date(2026, 11, 2))
        out = self.cycle(reader=FakeReader(fail=True), day=date(2026, 11, 30))
        stopped = [e for e in out["entries"] if e.status == "stopped" and e.reason.startswith("inaktuell")]
        self.assertTrue(stopped)

    def test_dashboard_and_questions(self):
        out = self.cycle()
        system = build_system(self.config, self.db, TEST_CONFIG)
        status = build_status(system, now="2026-11-02T00:00:00+00:00")
        self.assertEqual(status["scout"]["proposed"], 2)
        self.assertIn("scout-1", [a["id"] for a in status["agents"]])
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "q.md"
            q.write_text("# F\n")
            update_questions(q, ["godkänn eller avvisa förslaget x"], "2026-11-02")
            self.assertIn("Scouten väntar", q.read_text())


if __name__ == "__main__":
    unittest.main()
