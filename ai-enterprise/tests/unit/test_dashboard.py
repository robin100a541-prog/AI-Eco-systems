"""Fas 8: status.json (bara offentliga data, DR-13), fasta agentnamn och den dagliga cykeln (§56, §57)."""
import contextlib
import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from aie.config import load_config
from aie.dashboard.cycle import run as daily_cycle
from aie.dashboard.cycle import update_questions
from aie.dashboard.export import AGENT_FIELDS, build_status, check_public, ensure_names
from aie.memory import Database
from aie.monitoring import shutdown_logging
from aie.simulation.agents import ensure_org
from aie.system import build_system

from .fixture_config import TEST_CONFIG


class DashboardCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        self.dir = Path(tmp.name)


class TestStatus(DashboardCase):
    def setUp(self):
        super().setUp()
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.system = build_system(load_config(TEST_CONFIG), self.db, TEST_CONFIG)
        ensure_org(self.system.registry, "robin")

    def test_only_whitelisted_public_fields(self):
        status = build_status(self.system, now="2027-01-01T00:00:00+00:00")
        self.assertEqual(status["classification"], "public")
        for agent in status["agents"]:
            self.assertEqual(set(agent), set(AGENT_FIELDS))
        text = json.dumps(status)
        for forbidden in ("prompt", "api_key", "messages", "GROQ", "reasoning", "evidence"):
            self.assertNotIn(forbidden, text)
        self.assertIsNone(status["scoreboard"]["real"])  # riktiga pengar blandas aldrig in i SIM

    def test_secret_like_values_stop_the_export(self):
        with self.assertRaises(ValueError):
            check_public({"agents": [{"id": "x", "activity": "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"}]})
        with self.assertRaises(ValueError):
            check_public({"agents": [{"id": "x", "prompt": "hemligt"}]})

    def test_names_are_fixed_forever(self):
        first = ensure_names(self.db, ["ceo-1", "cfo-1"])
        self.assertEqual(ensure_names(self.db, ["cfo-1", "ceo-1", "new-1"])["ceo-1"], first["ceo-1"])
        with self.assertRaises(sqlite3.DatabaseError):
            with self.db.transaction() as tx:
                tx.execute("UPDATE agent_names SET first_name = 'X'")


class TestDailyCycle(DashboardCase):
    def setUp(self):
        super().setUp()
        self.config = self.dir / "config"
        shutil.copytree(TEST_CONFIG, self.config)
        text = (self.config / "system.toml").read_text()
        text = text.replace('data_dir = "data"', f'data_dir = "{(self.dir / "data").as_posix()}"')
        text = text.replace('log_dir = "logs"', f'log_dir = "{(self.dir / "logs").as_posix()}"')
        (self.config / "system.toml").write_text(text)
        self.questions = self.dir / "q.md"
        self.questions.write_text("# Frågor\n")

    def cycle(self, weekday=date(2026, 11, 3)):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = daily_cycle(self.config, "robin", "scripted", self.dir / "rep", self.dir / "dash" / "status.json",
                               self.questions, self.dir / "KILL", today=weekday)
        return code, out.getvalue()

    def test_cycle_writes_reports_and_status(self):
        code, text = self.cycle(weekday=date(2026, 11, 2))  # måndag: även veckorapport
        self.assertEqual(code, 0, text)
        self.assertTrue(list((self.dir / "rep" / "daily").glob("*.md")))
        self.assertTrue(list((self.dir / "rep" / "periodic").glob("*.md")))
        status = json.loads((self.dir / "dash" / "status.json").read_text())
        self.assertGreater(len(status["agents"]), 0)

    def test_kill_file_stops_agents_and_notifies_founders(self):
        self.cycle()
        (self.dir / "KILL").write_text("test av nödstopp")
        code, text = self.cycle()
        self.assertIn("Nödstopp: på", text)
        self.assertIn("nödstoppet är på", self.questions.read_text())
        self.assertTrue(json.loads((self.dir / "dash" / "status.json").read_text())["kill_switch"])
        (self.dir / "KILL").unlink()
        code, text = self.cycle()
        self.assertIn("Nödstopp: släppt", text)
        self.assertNotIn("nödstoppet är på", self.questions.read_text())

    def test_notice_is_replaced_not_duplicated(self):
        path = self.dir / "x.md"
        path.write_text("# F\n")
        update_questions(path, ["a"], "2027-01-01")
        update_questions(path, ["b"], "2027-01-02")
        text = path.read_text()
        self.assertEqual(text.count("daily-cycle:start"), 1)
        self.assertIn("- b", text)
        self.assertNotIn("- a", text)


if __name__ == "__main__":
    unittest.main()
