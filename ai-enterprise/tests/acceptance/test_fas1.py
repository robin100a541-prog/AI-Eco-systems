"""Acceptanstester för Fas 1 (konstitutionen §49, ROADMAP 1.7).

Ett test per acceptanskriterium i §49. Alla körs från början till slut med de riktiga
kommandona (`python -m aie ...`) i egna processer, i en tom temporär mapp, precis som en
användare gör. Inget testas genom att anropa interna funktioner.

§49 acceptanskriterier:
1. Systemet startar och avslutas korrekt.          → TestStartsAndStops
2. Konfigurationen kan läsas och valideras.        → TestConfigReadAndValidated
3. Fel loggas.                                     → TestErrorsLogged
4. Data överlever omstart.                         → TestDataSurvivesRestart
5. Tester kan köras reproducerbart.                → TestReproducible
ROADMAP 1.7 kräver dessutom att en manipulerad audit-rad upptäcks → TestTamperedAuditDetected.
"""

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 30


class Fas1Acceptance(unittest.TestCase):
    """Varje test får en egen tom mapp med en kopia av repots `config/`."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        shutil.copytree(ROOT / "config", self.dir / "config")
        self.env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
        }

    def aie(self, *args, timeout=TIMEOUT):
        """Kör `python -m aie ...` och väntar på resultatet."""
        return subprocess.run(
            [sys.executable, "-m", "aie", *args],
            cwd=self.dir,
            env=self.env,
            capture_output=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )

    def start(self):
        """Startar `python -m aie start` i bakgrunden och väntar tills `status` säger igång."""
        process = subprocess.Popen(
            [sys.executable, "-m", "aie", "start", "--poll-seconds", "0.1"],
            cwd=self.dir,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )
        self.addCleanup(self._reap, process)
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.fail(
                    f"start avslutades direkt med kod {process.returncode}: {process.stderr.read()}"
                )
            if "Status:         igång" in self.aie("status").stdout:
                return process
            time.sleep(0.1)
        self.fail("systemet blev aldrig igång")

    @staticmethod
    def _reap(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=TIMEOUT)

    def write_system(self, **changes):
        """Ändrar enstaka rader i kopian av config/system.toml."""
        path = self.dir / "config" / "system.toml"
        lines = path.read_text(encoding="utf-8").splitlines()
        for key, value in changes.items():
            lines = [
                f"{key} = {json.dumps(value)}" if line.startswith(f"{key} =") else line
                for line in lines
            ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def log_lines(self):
        path = self.dir / "logs" / "aie.log"
        return [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def audit_actions(self):
        with sqlite3.connect(self.dir / "data" / "sim.db") as conn:
            return [
                row[0]
                for row in conn.execute("SELECT action FROM audit_log ORDER BY seq")
            ]


class TestStartsAndStops(Fas1Acceptance):
    def test_start_stop_with_commands(self):
        """§49 kriterium 1 (FR-01): init, start, stop och status fungerar och ger kod 0; nedstängningen är ren."""
        self.assertEqual(self.aie("init").returncode, 0)
        process = self.start()
        stop = self.aie("stop")
        self.assertEqual(stop.returncode, 0, stop.stderr)
        out, err = process.communicate(timeout=TIMEOUT)
        self.assertEqual(process.returncode, 0, err)
        self.assertIn("Systemet har stängts ned.", out)
        status = self.aie("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("Status:         stoppad", status.stdout)
        self.assertIn("Senaste avslut: clean", status.stdout)

    @unittest.skipIf(
        sys.platform == "win32",
        "SIGINT till en annan process fungerar inte så på Windows",
    )
    def test_ctrl_c_stops_cleanly(self):
        """§49 kriterium 1 (FR-01): Ctrl+C stänger ned rent med kod 0, utan traceback."""
        process = self.start()
        process.send_signal(signal.SIGINT)
        _, err = process.communicate(timeout=TIMEOUT)
        self.assertEqual(process.returncode, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertIn("Senaste avslut: clean", self.aie("status").stdout)


class TestConfigReadAndValidated(Fas1Acceptance):
    def test_valid_config_accepted(self):
        """§49 kriterium 2 (FR-02): repots konfiguration läses och godkänns."""
        result = self.aie("check-config")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Konfiguration OK", result.stdout)

    def test_invalid_config_rejected_with_all_errors_and_start_refused(self):
        """§49 kriterium 2 (FR-02): en ogiltig konfiguration listar alla fel, och systemet startar inte."""
        self.write_system(environment="prod", log_level="LOUD")
        check = self.aie("check-config")
        self.assertEqual(check.returncode, 1)
        self.assertIn("base_currency = 'SIM' är inte tillåtet i prod", check.stderr)
        self.assertIn("log_level = 'LOUD' är okänd", check.stderr)
        start = self.aie("start")
        self.assertEqual(start.returncode, 1)
        self.assertFalse(
            (self.dir / "data").exists(),
            "ingen databas får skapas med ogiltig konfiguration",
        )


class TestErrorsLogged(Fas1Acceptance):
    def test_config_errors_logged(self):
        """§49 kriterium 3 (FR-04): konfigurationsfel loggas i loggfilen med tid, nivå och källa."""
        self.write_system(environment="prod")
        self.assertEqual(self.aie("start").returncode, 1)
        errors = [e for e in self.log_lines() if e["level"] == "ERROR"]
        self.assertTrue(errors)
        self.assertTrue(all({"ts", "source", "message"} <= set(e) for e in errors))
        self.assertTrue(any("base_currency = 'SIM'" in e["message"] for e in errors))

    def test_storage_error_logged(self):
        """§49 kriterium 3 (FR-04): en data_dir som inte kan skapas ger kod 1 och loggas som fel."""
        (self.dir / "blockerad").write_text("en fil, ingen mapp", encoding="utf-8")
        self.write_system(data_dir="blockerad/data")
        result = self.aie("start")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        errors = [
            e
            for e in self.log_lines()
            if e["level"] == "ERROR" and e["source"] == "aie.memory"
        ]
        self.assertTrue(any("kan inte öppnas" in e["message"] for e in errors), errors)

    def test_secrets_never_logged(self):
        """§49 kriterium 3 (SR-10): en hemlighet i miljön syns aldrig i loggen, inte ens vid fel."""
        secret = "gsk_ACCEPTANS_HEMLIG_NYCKEL"
        self.env["GROQ_API_KEY"] = secret
        self.write_system(environment="prod")
        self.aie("start")
        self.assertNotIn(
            secret, (self.dir / "logs" / "aie.log").read_text(encoding="utf-8")
        )


class TestDataSurvivesRestart(Fas1Acceptance):
    def test_two_runs_keep_all_data(self):
        """§49 kriterium 4 (FR-03): allt från första körningen finns kvar efter omstart, och kedjan är intakt."""
        for _ in range(2):
            process = self.start()
            self.assertEqual(self.aie("stop").returncode, 0)
            process.communicate(timeout=TIMEOUT)
        self.assertEqual(
            self.audit_actions(),
            ["system.start", "system.stop_requested", "system.stop"] * 2,
        )
        status = self.aie("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("Revisionslogg:  OK, 6 rader", status.stdout)

    def test_unclean_stop_recovered_without_data_loss(self):
        """§49 kriterium 4 (FR-01, FR-03): en process som dödas utan nedstängning; nästa start fortsätter utan dataförlust."""
        process = self.start()
        process.kill()  # som ett strömavbrott: ingen nedstängning
        process.communicate(timeout=TIMEOUT)
        process = self.start()
        self.assertEqual(self.aie("stop").returncode, 0)
        process.communicate(timeout=TIMEOUT)
        actions = self.audit_actions()
        self.assertEqual(actions[0], "system.start")
        self.assertIn("system.unclean_stop_detected", actions)
        self.assertIn("Revisionslogg:  OK", self.aie("status").stdout)


class TestTamperedAuditDetected(Fas1Acceptance):
    def test_tampered_row_detected_and_start_refused(self):
        """ROADMAP 1.7 (SR-09): en ändrad audit-rad upptäcks av status, och systemet vägrar starta."""
        self.assertEqual(self.aie("init").returncode, 0)
        with sqlite3.connect(
            self.dir / "data" / "sim.db"
        ) as conn:  # som en angripare med filåtkomst
            conn.execute("DROP TRIGGER audit_log_no_update")
            conn.execute("UPDATE audit_log SET action = 'förfalskad' WHERE seq = 1")
        status = self.aie("status")
        self.assertEqual(status.returncode, 1)
        self.assertIn("MANIPULERAD vid rad 1", status.stderr)
        start = self.aie("start")
        self.assertEqual(start.returncode, 1)
        self.assertIn("revisionsloggen är manipulerad", start.stderr)


class TestReproducible(Fas1Acceptance):
    def test_no_network_no_third_party_imports(self):
        """§49 kriterium 5 (D-002): koden använder bara standardbiblioteket, så testerna kräver ingen installation."""
        stdlib = set(sys.stdlib_module_names)
        for path in (ROOT / "src").rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                words = line.split()
                if (
                    len(words) >= 2
                    and words[0] in ("import", "from")
                    and not words[1].startswith(".")
                ):
                    top = words[1].split(".")[0].rstrip(",")
                    self.assertIn(
                        top,
                        stdlib | {"aie", "__future__"},
                        f"{path.name}: {line.strip()}",
                    )

    def test_tests_leave_no_files_in_repo(self):
        """§49 kriterium 5: acceptanstesterna skriver bara i temporära mappar, aldrig i repot."""
        before = {p for p in ROOT.rglob("*") if "__pycache__" not in p.parts}
        self.aie("init")
        self.aie("status")
        after = {p for p in ROOT.rglob("*") if "__pycache__" not in p.parts}
        self.assertEqual(after - before, set())


if __name__ == "__main__":
    unittest.main()
