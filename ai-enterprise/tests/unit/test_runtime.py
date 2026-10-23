"""Tester för src/aie/runtime.py och kommandona init/start/stop/status (Fas 1.6).

Verifierar FR-01 (start, stopp, omstart), FR-02 (fel i konfigurationen stoppar start),
FR-03 (data överlever omstart), FR-04 (fel loggas) och SR-09 (manipulerad revisionslogg
stoppar start). En del tester kör `start` i en tråd i samma process, andra startar en
riktig process med `python -m aie` precis som en användare gör.
"""

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from aie import runtime
from aie.audit import AuditLog
from aie.memory import Database
from aie.monitoring import LOG_FILE_NAME, shutdown_logging

from .test_config import VALID_RISK, VALID_SYSTEM, _merge, _toml

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 20  # sekunder; generöst så att långsamma CI-maskiner inte ger falska fel


class RuntimeTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.addCleanup(shutdown_logging)  # körs före cleanup av mappen (LIFO)
        self.config_dir = self.write_config()

    def write_config(self, **system_changes):
        config_dir = self.dir / "config"
        config_dir.mkdir(exist_ok=True)
        system = _merge(
            VALID_SYSTEM,
            {
                "data_dir": str(self.dir / "data"),
                "log_dir": str(self.dir / "logs"),
                **system_changes,
            },
        )
        (config_dir / "system.toml").write_text(_toml(system), encoding="utf-8")
        (config_dir / "risk_limits.toml").write_text(
            _toml(VALID_RISK), encoding="utf-8"
        )
        return config_dir

    def db(self):
        db = Database.open(self.dir / "data", "sim")
        self.addCleanup(db.close)
        return db

    def actions(self):
        with Database.open(self.dir / "data", "sim") as db:
            return [e.action for e in AuditLog(db).entries()]

    def state(self):
        with Database.open(self.dir / "data", "sim") as db:
            return runtime.read_state(db)

    def log_entries(self):
        shutdown_logging()
        path = self.dir / "logs" / LOG_FILE_NAME
        return [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def quiet(self, func, *args, **kwargs):
        """Kör ett kommando i samma process och fångar dess utskrifter."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = func(*args, **kwargs)
        shutdown_logging()
        return code, out.getvalue(), err.getvalue()

    def run_in_thread(self, on_running=None):
        """Startar systemet i en tråd. Returnerar (stop_event, tråd, resultat-lista)."""
        stop_event, running, result = threading.Event(), threading.Event(), []

        def started():
            running.set()
            if on_running:
                on_running()

        def target():
            result.append(
                self.quiet(
                    runtime.start,
                    self.config_dir,
                    0.05,
                    stop_event=stop_event,
                    on_running=started,
                )
            )

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        if on_running is None:
            self.assertTrue(running.wait(TIMEOUT), "systemet startade inte")
        return stop_event, thread, result


class TestStartStopInProcess(RuntimeTestCase):
    def test_start_then_stop_is_clean(self):
        """Verifies FR-01: systemet startar, markeras som igång och stängs ned rent med kod 0."""
        stop_event, thread, result = self.run_in_thread()
        self.assertEqual(self.state().state, "running")
        self.assertEqual(self.state().pid, os.getpid())
        stop_event.set()
        thread.join(TIMEOUT)
        code, out, _ = result[0]
        self.assertEqual(code, 0)
        self.assertIn("Systemet har stängts ned.", out)
        state = self.state()
        self.assertEqual(
            (state.state, state.last_exit, state.pid), ("stopped", "clean", None)
        )
        self.assertEqual(self.actions(), ["system.start", "system.stop"])

    def test_data_survives_restart(self):
        """Verifies FR-01, FR-03: två körningar efter varandra; allt från den första finns kvar."""
        for _ in range(2):
            stop_event, thread, _ = self.run_in_thread()
            stop_event.set()
            thread.join(TIMEOUT)
        self.assertEqual(
            self.actions(),
            ["system.start", "system.stop", "system.start", "system.stop"],
        )
        with Database.open(self.dir / "data", "sim") as db:
            self.assertTrue(AuditLog(db).verify().ok)

    def test_unexpected_error_is_logged_and_shuts_down(self):
        """Verifies FR-04: ett oväntat fel loggas med traceback, ger kod 1 och stänger ändå ned."""

        def crash():
            raise RuntimeError("något gick sönder")

        _, thread, result = self.run_in_thread(on_running=crash)
        thread.join(TIMEOUT)
        code, _, err = result[0]
        self.assertEqual(code, 1)
        self.assertIn("oväntat fel", err)
        state = self.state()
        self.assertEqual((state.state, state.last_exit), ("stopped", "error"))
        errors = [e for e in self.log_entries() if e["level"] == "ERROR"]
        self.assertTrue(
            any(
                "RuntimeError: något gick sönder" in e.get("exception", "")
                for e in errors
            ),
            errors,
        )
        self.assertEqual(self.actions()[-1], "system.stop")


class TestStartRefused(RuntimeTestCase):
    def test_config_error_stops_start_and_is_logged(self):
        """Verifies FR-02, FR-04: ogiltig konfiguration ger kod 1, felen skrivs ut och loggas, inget startas."""
        self.write_config(environment="prod")  # prod med valutan SIM är ogiltigt
        cwd = os.getcwd()
        os.chdir(self.dir)  # felen loggas i logs/ i arbetsmappen när log_dir är okänd
        self.addCleanup(os.chdir, cwd)
        code, _, err = self.quiet(runtime.start, self.config_dir)
        self.assertEqual(code, 1)
        self.assertIn("base_currency = 'SIM' är inte tillåtet i prod", err)
        self.assertFalse((self.dir / "data").exists())
        logged = [e["message"] for e in self.log_entries() if e["level"] == "ERROR"]
        self.assertTrue(any("base_currency = 'SIM'" in m for m in logged), logged)

    def test_tampered_audit_log_stops_start(self):
        """Verifies SR-09: en manipulerad revisionslogg gör att systemet vägrar starta."""
        self.assertEqual(self.quiet(runtime.init, self.config_dir)[0], 0)
        with self.db().transaction() as tx:
            tx.execute("DROP TRIGGER audit_log_no_update")
            tx.execute("UPDATE audit_log SET action = 'förfalskad' WHERE seq = 1")
        code, _, err = self.quiet(runtime.start, self.config_dir)
        self.assertEqual(code, 1)
        self.assertIn("revisionsloggen är manipulerad vid rad 1", err)
        self.assertEqual(self.state().state, "stopped")

    def test_second_start_refused_while_running(self):
        """Verifies FR-01: en andra start vägras medan systemet redan kör, och läget ändras inte."""
        self.quiet(runtime.init, self.config_dir)
        with (
            self.db().transaction() as tx
        ):  # en levande process (testet självt) markeras som igång
            tx.execute(
                "UPDATE runtime_state SET state = 'running', pid = ? WHERE id = 1",
                (os.getppid(),),
            )
        code, _, err = self.quiet(runtime.start, self.config_dir)
        self.assertEqual(code, 1)
        self.assertIn("redan igång", err)
        self.assertEqual(self.state().pid, os.getppid())

    def test_unclean_previous_run_is_recovered(self):
        """Verifies FR-01: en körning som dog utan nedstängning upptäcks, revideras och start fortsätter."""
        dead_pid = 2**22 + 12345  # över Linux pid_max-standard; finns inte
        self.quiet(runtime.init, self.config_dir)
        with self.db().transaction() as tx:
            tx.execute(
                "UPDATE runtime_state SET state = 'running', pid = ? WHERE id = 1",
                (dead_pid,),
            )
        stop_event, thread, _ = self.run_in_thread()
        stop_event.set()
        thread.join(TIMEOUT)
        self.assertIn("system.unclean_stop_detected", self.actions())
        self.assertEqual(self.state().last_exit, "clean")


class TestStopAndStatus(RuntimeTestCase):
    def test_stop_when_not_running(self):
        """Verifies FR-01: stop när systemet inte kör ger kod 0 och ett tydligt besked."""
        code, out, _ = self.quiet(runtime.stop, self.config_dir)
        self.assertEqual(code, 0)
        self.assertIn("inte igång", out)

    def test_stop_times_out_with_exit_1(self):
        """Verifies FR-01, FR-04: om systemet inte stannar i tid ger stop kod 1 och loggar felet."""
        self.quiet(runtime.init, self.config_dir)
        with (
            self.db().transaction() as tx
        ):  # en levande process som aldrig läser stoppbegäran
            tx.execute(
                "UPDATE runtime_state SET state = 'running', pid = ? WHERE id = 1",
                (os.getppid(),),
            )
        code, _, err = self.quiet(runtime.stop, self.config_dir, 0.3)
        self.assertEqual(code, 1)
        self.assertIn("stoppade inte inom", err)

    def test_status_reports_tampering_with_exit_1(self):
        """Verifies SR-09: status upptäcker en manipulerad revisionsrad och ger kod 1."""
        self.quiet(runtime.init, self.config_dir)
        code, out, _ = self.quiet(runtime.status, self.config_dir)
        self.assertEqual(code, 0)
        self.assertIn("Revisionslogg:  OK, 1 rader", out)
        with self.db().transaction() as tx:
            tx.execute("DROP TRIGGER audit_log_no_delete")
            tx.execute("DELETE FROM audit_log WHERE seq = 1")
            tx.execute(
                "INSERT INTO audit_log (seq, timestamp, actor, action, details, prev_hash, hash) "
                "VALUES (2, 't', 'x', 'y', '{}', 'p', 'h')"
            )
        code, _, err = self.quiet(runtime.status, self.config_dir)
        self.assertEqual(code, 1)
        self.assertIn("MANIPULERAD", err)

    def test_pid_alive(self):
        """Verifies FR-01: en levande process känns igen, en process som inte finns gör det inte."""
        self.assertTrue(runtime.pid_alive(os.getpid()))
        self.assertFalse(runtime.pid_alive(2**22 + 12345))
        self.assertFalse(runtime.pid_alive(0))


class TestRealProcess(RuntimeTestCase):
    """Startar `python -m aie start` som en egen process, precis som en användare gör."""

    def cli(self, *args, **kwargs):
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
        }
        return subprocess.Popen(
            [sys.executable, "-m", "aie", *args, "--config-dir", str(self.config_dir)],
            cwd=self.dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            **kwargs,
        )

    @staticmethod
    def reap(process):
        """Stoppar processen om den lever och stänger dess rör, även när ett test har fallerat."""
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=TIMEOUT)

    def start_process(self):
        process = self.cli("start", "--poll-seconds", "0.1")
        self.addCleanup(self.reap, process)
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            if (
                self.dir / "data" / "sim.db"
            ).exists() and self.state().state == "running":
                return process
            self.assertIsNone(
                process.poll(),
                process.stderr.read() if process.poll() is not None else "",
            )
            time.sleep(0.05)
        self.fail("systemet blev aldrig igång")

    def test_cli_start_stop_status(self):
        """Verifies FR-01: `aie start` i en process, `aie stop` i en annan; båda ger kod 0 och nedstängningen är ren."""
        process = self.start_process()
        status = self.cli("status")
        out, _ = status.communicate(timeout=TIMEOUT)
        self.assertIn("igång (pid", out)
        stop = self.cli("stop")
        stop_out, stop_err = stop.communicate(timeout=TIMEOUT)
        self.assertEqual(stop.returncode, 0, stop_err)
        self.assertIn("Systemet har stoppats.", stop_out)
        out, err = process.communicate(timeout=TIMEOUT)
        self.assertEqual(process.returncode, 0, err)
        self.assertIn("Systemet har stängts ned.", out)
        self.assertEqual(self.state().last_exit, "clean")
        self.assertEqual(
            self.actions(), ["system.start", "system.stop_requested", "system.stop"]
        )

    @unittest.skipIf(
        sys.platform == "win32",
        "SIGINT till en annan process fungerar inte så på Windows",
    )
    def test_ctrl_c_shuts_down_cleanly(self):
        """Verifies FR-01: Ctrl+C (SIGINT) stänger ned rent med kod 0 i stället för att avbryta."""
        process = self.start_process()
        process.send_signal(signal.SIGINT)
        _, err = process.communicate(timeout=TIMEOUT)
        self.assertEqual(process.returncode, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.state().last_exit, "clean")


if __name__ == "__main__":
    unittest.main()
