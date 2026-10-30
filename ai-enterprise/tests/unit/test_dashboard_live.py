"""Live telemetry never adds inference, reveals work text or changes company outcomes."""
import json
import time
from pathlib import Path
from unittest.mock import patch

from aie.dashboard.export import build_status, write_status
from aie.dashboard.live import LiveStatus
from aie.llm import ChatRequest, DataClass, Message
from aie.simulation.cli import simulate
from . import test_dashboard as dashboard_fixtures


class TestLive(dashboard_fixtures.DashboardCase):
    def setUp(self):
        super().setUp()
        from aie.config import load_config
        from aie.memory import Database
        from aie.system import build_system
        from aie.simulation.agents import ensure_org
        from .fixture_config import TEST_CONFIG

        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.system = build_system(load_config(TEST_CONFIG), self.db, TEST_CONFIG)
        ensure_org(self.system.registry, "robin")

    def observer(self):
        return LiveStatus(self.system, self.dir / "status.json", "scripted")

    def read(self):
        return json.loads((self.dir / "status.json").read_text())

    def test_roles_have_public_plan_but_no_fictional_current_work(self):
        snapshot = build_status(self.system)
        self.assertFalse(snapshot["meeting"])
        self.assertEqual(snapshot["execution"]["state"], "offline")
        self.assertIn("Undersök", next(a["work"]["next"] for a in snapshot["agents"] if a["role"] == "researcher"))
        for a in snapshot["agents"]:
            self.assertEqual(a["work"]["phase"], "idle")

    def test_gateway_delegates_once_and_never_exports_prompt_or_response(self):
        request = ChatRequest((Message("user", "PRIVATE_CUSTOMER_TEXT"),), DataClass.INTERNAL)
        class Gateway:
            calls = 0
            def complete(inner, actor, received):
                inner.calls += 1
                self.assertIs(received, request)
                self.assertEqual(next(a["work"]["phase"] for a in self.read()["agents"] if a["id"] == actor), "thinking")
                return "PRIVATE_MODEL_RESPONSE"
        gateway = Gateway()
        with self.observer() as obs:
            self.assertEqual(obs.gateway(gateway).complete("res-1", request), "PRIVATE_MODEL_RESPONSE")
            self.assertEqual(self.read()["execution"]["state"], "running")
        self.assertEqual(gateway.calls, 1)
        text = (self.dir / "status.json").read_text()
        self.assertNotIn("PRIVATE_", text)
        self.assertEqual(self.read()["execution"]["state"], "finished")

    def test_exception_stops_session_and_closes_meeting_without_swallowing_error(self):
        with self.assertRaisesRegex(RuntimeError, "private reason"):
            with self.observer() as obs:
                with obs.meeting(["cfo-1", "cro-1"]):
                    self.assertEqual(self.read()["meetings"][0]["participants"], ["cfo-1", "cro-1"])
                    raise RuntimeError("private reason")
        snapshot = self.read()
        self.assertFalse(snapshot["meeting"])
        self.assertEqual(snapshot["execution"]["state"], "failed")
        self.assertNotIn("private reason", json.dumps(snapshot))

    def test_heartbeat_uses_cached_snapshot_without_cross_thread_sqlite(self):
        with self.observer() as obs:
            before = self.read()["execution"]["heartbeat_at"]
            with patch("aie.dashboard.live.build_status", side_effect=AssertionError("SQLite on heartbeat thread")):
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and self.read()["execution"]["heartbeat_at"] == before:
                    time.sleep(.05)
            self.assertNotEqual(self.read()["execution"]["heartbeat_at"], before)
        self.assertFalse(obs._thread.is_alive())

    def test_export_failure_cannot_fail_or_repeat_model_work(self):
        class Gateway:
            calls = 0
            def complete(inner, *args):
                inner.calls += 1
                return "answer"
        gateway = Gateway()
        with patch("aie.dashboard.live.write_status", side_effect=OSError("disk full")):
            with self.observer() as obs:
                self.assertEqual(obs.gateway(gateway).complete("res-1", object()), "answer")
        self.assertEqual(gateway.calls, 1)

    def test_only_one_process_can_own_a_dashboard_file(self):
        with self.observer() as first:
            with self.observer() as second:
                second.agent("res-1", "fetching")
                self.assertIsNone(second.out)
                self.assertEqual(self.read()["execution"]["session_id"], first.session)
        with self.observer() as third:
            self.assertEqual(self.read()["execution"]["session_id"], third.session)

    def test_atomic_write_preserves_previous_valid_snapshot_on_failure(self):
        target = self.dir / "atomic.json"
        write_status({"classification": "public"}, target)
        previous = target.read_bytes()
        with patch("aie.dashboard.export.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                write_status({"classification": "public", "new": True}, target)
        self.assertEqual(target.read_bytes(), previous)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


class TestLiveCycle(dashboard_fixtures.TestDailyCycle):
    def test_real_scripted_cycle_exports_steps_and_finishes(self):
        observed = []
        original = LiveStatus.publish
        def record(obs):
            original(obs)
            if obs.out and obs.out.exists():
                observed.append(json.loads(obs.out.read_text()))
        with patch.object(LiveStatus, "publish", record):
            code = simulate(self.config, "start", "normal", "robin", 1, "scripted",
                            dashboard=self.dir / "live.json")
        self.assertEqual(code, 0)
        phases = {a["work"]["phase"] for s in observed for a in s["agents"]}
        self.assertTrue({"queued", "thinking", "checking", "done"} <= phases)
        self.assertEqual(observed[-1]["execution"]["state"], "finished")

    def test_conflict_cycle_emits_only_actual_assessment_participants(self):
        meetings = []
        original = LiveStatus.publish
        def record(obs):
            original(obs)
            if obs.meetings:
                meetings.append(obs.meetings[0]["participants"])
        with patch.object(LiveStatus, "publish", record):
            code = simulate(self.config, "start", "conflict", "robin", 4, "scripted",
                            dashboard=self.dir / "live.json")
        self.assertEqual(code, 0)
        self.assertTrue(meetings)
        self.assertTrue(all(set(m) == {"cfo-1", "cro-1", "ceo-1"} for m in meetings))
        self.assertFalse(json.loads((self.dir / "live.json").read_text())["meeting"])
