"""Tester för src/aie/monitoring (Fas 1.3) och loggningen i `python -m aie check-config`.

Verifierar FR-02, FR-04 och SR-10. Varje test skriver loggar i en egen temporär mapp,
och handlers stängs efter varje test så att filerna släpps (Windows).
"""

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aie.config import ConfigError, load_config
from aie.monitoring import (
    LOG_FILE_NAME,
    LoggingSetupError,
    get_logger,
    mask_secrets,
    setup_logging,
    shutdown_logging,
)

from .test_config import VALID_RISK, VALID_SYSTEM, _merge, _toml

ROOT = Path(__file__).resolve().parents[2]
SECRET = "gsk_TEST_SECRET_SHOULD_NOT_LEAK"


class LoggingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.addCleanup(shutdown_logging)  # körs före cleanup av mappen (LIFO)
        self.console = io.StringIO()

    def setup(self, level="INFO", log_dir=None):
        return setup_logging(log_dir or self.dir / "logs", level, stream=self.console)

    def log_lines(self, log_dir=None):
        for handler in logging.getLogger("aie").handlers:
            handler.flush()
        path = (log_dir or self.dir / "logs") / LOG_FILE_NAME
        return [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def all_output(self):
        log_file = self.dir / "logs" / LOG_FILE_NAME
        return log_file.read_text(encoding="utf-8") + self.console.getvalue()


class TestFileAndConsole(LoggingTestCase):
    def test_event_written_to_file_as_json_with_timestamp_and_source(self):
        """Verifies FR-04: en händelse skrivs till log_dir/aie.log med tidsstämpel, nivå och källa."""
        self.setup()
        get_logger("test").info("hej %s", "världen")
        [entry] = self.log_lines()
        self.assertEqual(entry["message"], "hej världen")
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["source"], "aie.test")
        self.assertRegex(entry["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$")
        self.assertIn("test_logging:", entry["where"])

    def test_event_also_written_to_console(self):
        """Verifies FR-04: samma händelse visas i konsolen som läsbar text med nivå och källa."""
        self.setup()
        get_logger("test").warning("varning här")
        self.assertRegex(
            self.console.getvalue(), r"\d\d:\d\d:\d\d WARNING aie\.test: varning här"
        )

    def test_structured_fields_are_kept(self):
        """Verifies FR-04: fält i extra={"fields": ...} sparas strukturerat i JSON-raden."""
        self.setup()
        get_logger("test").info(
            "uppgift", extra={"fields": {"task_id": 7, "agent": "CFO"}}
        )
        [entry] = self.log_lines()
        self.assertEqual(entry["fields"], {"task_id": 7, "agent": "CFO"})

    def test_missing_log_dir_is_created(self):
        """Verifies FR-04: en saknad log_dir skapas automatiskt, även nästlade mappar."""
        log_dir = self.dir / "a" / "b" / "logs"
        self.assertFalse(log_dir.exists())
        self.setup(log_dir=log_dir)
        get_logger().info("start")
        self.assertTrue((log_dir / LOG_FILE_NAME).is_file())
        self.assertEqual(self.log_lines(log_dir)[0]["message"], "start")

    def test_new_setup_does_not_duplicate_lines(self):
        """Verifies FR-04: att starta loggningen två gånger skriver inte samma händelse två gånger."""
        self.setup()
        self.setup()
        get_logger().info("en gång")
        self.assertEqual(len(self.log_lines()), 1)
        self.assertEqual(self.console.getvalue().count("en gång"), 1)


class TestLevel(LoggingTestCase):
    def test_level_warning_drops_info_and_debug(self):
        """Verifies FR-04: med log_level WARNING skrivs bara WARNING och högre, i fil och konsol."""
        self.setup("WARNING")
        log = get_logger("test")
        log.debug("debug-rad")
        log.info("info-rad")
        log.warning("warning-rad")
        log.error("error-rad")
        self.assertEqual(
            [e["message"] for e in self.log_lines()], ["warning-rad", "error-rad"]
        )
        self.assertNotIn("info-rad", self.console.getvalue())

    def test_level_debug_includes_debug(self):
        """Verifies FR-04: med log_level DEBUG skrivs även DEBUG."""
        self.setup("DEBUG")
        get_logger("test").debug("debug-rad")
        self.assertEqual(self.log_lines()[0]["level"], "DEBUG")

    def test_log_level_read_from_system_toml(self):
        """Verifies FR-02: log_level läses från system.toml; saknas den gäller INFO."""
        config_dir = self.dir / "config"
        _write_config(config_dir, log_level="ERROR")
        self.assertEqual(load_config(config_dir).system.log_level, "ERROR")
        _write_config(config_dir)
        self.assertEqual(load_config(config_dir).system.log_level, "INFO")
        self.assertEqual(load_config(ROOT / "config").system.log_level, "INFO")

    def test_unknown_log_level_is_config_error(self):
        """Verifies FR-02: en okänd log_level stoppar uppstart med ett tydligt fel."""
        config_dir = self.dir / "config"
        _write_config(config_dir, log_level="LOUD")
        with self.assertRaises(ConfigError) as ctx:
            load_config(config_dir)
        self.assertIn("log_level = 'LOUD' är okänd", "\n".join(ctx.exception.errors))


class TestSecretsMasked(LoggingTestCase):
    def test_secret_key_value_in_message_is_masked(self):
        """Verifies SR-10: värden för *_KEY, *_TOKEN, *_SECRET och password i text visas aldrig."""
        self.setup()
        log = get_logger("test")
        log.info("GROQ_API_KEY=%s", SECRET)
        log.info("anrop med access_token: %s klart", SECRET)
        log.info('{"client_secret": "%s"}', SECRET)
        log.info("password = '%s'", SECRET)
        output = self.all_output()
        self.assertNotIn(SECRET, output)
        self.assertIn("GROQ_API_KEY=***", output)
        self.assertIn("access_token: *** klart", output)

    def test_secret_fields_are_masked_also_nested(self):
        """Verifies SR-10: hemliga nycklar i strukturerade fält maskeras, även i nästlade tabeller."""
        self.setup()
        get_logger("test").info(
            "leverantör",
            extra={
                "fields": {
                    "provider": "groq",
                    "auth": {"api_key": SECRET},
                    "Password": SECRET,
                }
            },
        )
        self.assertNotIn(SECRET, self.all_output())
        [entry] = self.log_lines()
        self.assertEqual(
            entry["fields"],
            {"provider": "groq", "auth": {"api_key": "***"}, "Password": "***"},
        )

    def test_secret_from_environment_masked_in_exception(self):
        """Verifies SR-10: värdet av en hemlig miljövariabel maskeras var det än står, även i en traceback."""
        self.setup()
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": SECRET}):
            try:
                raise RuntimeError(f"401 Unauthorized för nyckeln {SECRET}")
            except RuntimeError:
                get_logger("test").exception("anropet misslyckades")
        self.assertNotIn(SECRET, self.all_output())
        self.assertIn(
            "401 Unauthorized för nyckeln ***", self.log_lines()[0]["exception"]
        )

    def test_ordinary_words_are_not_masked(self):
        """Verifies SR-10: maskeringen tar bara hemligheter, inte vanliga ord som innehåller 'key'."""
        text = "monkey=3 keyboard: sv task_id=7 base_currency=SIM"
        self.assertEqual(mask_secrets(text, environ={}), text)


class TestRotation(LoggingTestCase):
    def test_log_file_rotates_and_keeps_limited_backups(self):
        """Verifies FR-04: loggfilen roteras vid storleksgränsen och bara backup_count gamla filer sparas."""
        log_dir = self.dir / "logs"
        setup_logging(log_dir, console=False, max_bytes=1000, backup_count=2)
        log = get_logger("test")
        for i in range(200):  # cirka 30 kB, långt över 3 × 1000 byte
            log.info("rad %03d", i)
        shutdown_logging()

        names = sorted(p.name for p in log_dir.iterdir())
        self.assertEqual(
            names, [LOG_FILE_NAME, f"{LOG_FILE_NAME}.1", f"{LOG_FILE_NAME}.2"]
        )
        for path in log_dir.iterdir():
            self.assertLessEqual(path.stat().st_size, 1000, path.name)
        newest = (log_dir / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(newest[-1])["message"], "rad 199")

    def test_default_limits_are_bounded(self):
        """Verifies FR-04: standardinställningen begränsar loggarna (5 MB per fil, 3 gamla filer)."""
        self.setup()
        [handler] = [
            h for h in logging.getLogger("aie").handlers if hasattr(h, "maxBytes")
        ]
        self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
        self.assertEqual(handler.backupCount, 3)


class TestBadLogDir(LoggingTestCase):
    def test_log_dir_that_is_a_file_gives_clear_error(self):
        """Verifies FR-02: om log_dir inte kan skapas blir det ett tydligt fel med sökvägen."""
        blocker = self.dir / "inte_en_mapp"
        blocker.write_text("x", encoding="utf-8")
        for log_dir in (blocker, blocker / "logs"):
            with self.subTest(log_dir=log_dir):
                with self.assertRaises(LoggingSetupError) as ctx:
                    setup_logging(log_dir, stream=self.console)
                self.assertIn(str(log_dir), str(ctx.exception))
                self.assertIn("kan inte skapas", str(ctx.exception))


class TestCliLogging(LoggingTestCase):
    """CLI:t körs i en egen process med den temporära mappen som arbetsmapp."""

    def run_cli(self, config_dir):
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
        }
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "aie",
                "check-config",
                "--config-dir",
                str(config_dir),
            ],
            cwd=self.dir,
            env=env,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    def file_entries(self, log_dir):
        path = self.dir / log_dir / LOG_FILE_NAME
        return [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def test_cli_bad_log_dir_exit_1_with_clear_message(self):
        """Verifies FR-02: en log_dir som inte kan skapas ger kod 1 och ett tydligt fel, ingen traceback."""
        (self.dir / "blockerad").write_text("x", encoding="utf-8")
        _write_config(self.dir / "config", log_dir="blockerad/logs")
        result = self.run_cli(self.dir / "config")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FEL: log_dir", result.stderr)
        self.assertIn("kan inte skapas", result.stderr)
        self.assertNotIn("Konfiguration OK", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_valid_config_is_logged_to_log_dir(self):
        """Verifies FR-04: check-config skapar log_dir från system.toml och loggar resultatet."""
        _write_config(self.dir / "config", log_dir="mina_loggar")
        result = self.run_cli(self.dir / "config")
        self.assertEqual(result.returncode, 0, result.stderr)
        [entry] = self.file_entries("mina_loggar")
        self.assertEqual(entry["source"], "aie.cli")
        self.assertIn("konfigurationen är giltig", entry["message"])

    def test_cli_config_errors_are_logged_and_printed(self):
        """Verifies FR-02, FR-04: konfigurationsfel skrivs ut och loggas i logs/ i arbetsmappen."""
        _write_config(self.dir / "config", environment="prod", log_level="LOUD")
        result = self.run_cli(self.dir / "config")
        self.assertEqual(result.returncode, 1)
        self.assertIn("log_level = 'LOUD' är okänd", result.stderr)
        messages = [
            e["message"] for e in self.file_entries("logs") if e["level"] == "ERROR"
        ]
        self.assertTrue(
            any("log_level = 'LOUD' är okänd" in m for m in messages), messages
        )
        self.assertTrue(
            any("base_currency = 'SIM' är inte tillåtet i prod" in m for m in messages),
            messages,
        )


def _write_config(config_dir: Path, **system_changes) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "system.toml").write_text(
        _toml(_merge(VALID_SYSTEM, system_changes)), encoding="utf-8"
    )
    (config_dir / "risk_limits.toml").write_text(_toml(VALID_RISK), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
