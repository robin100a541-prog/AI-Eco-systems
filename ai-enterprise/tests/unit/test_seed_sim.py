"""Testdata i SIM för kommandocentralen (dashboard D0b): `scripts/seed_sim.py` och `aie.simulation.seed`."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from aie import runtime
from aie.governance.cli import build as build_governance
from aie.governance.escalation import RequestStatus
from aie.monitoring import shutdown_logging
from aie.simulation.run import SimulationError
from aie.simulation.seed import seed

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_sim", ROOT / "scripts" / "seed_sim.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeedCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        self.dir = Path(tmp.name)
        self.config_dir = self.dir / "config"
        shutil.copytree(CONFIG, self.config_dir)
        self.edit_system('data_dir = "data"', f'data_dir = "{(self.dir / "data").as_posix()}"')
        self.edit_system('log_dir = "logs"', f'log_dir = "{(self.dir / "logs").as_posix()}"')

    def edit_system(self, old, new):
        path = self.config_dir / "system.toml"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def seed(self, **kwargs):
        try:
            return seed(self.config_dir, **kwargs)
        finally:
            shutdown_logging()


class TestSeed(SeedCase):
    def test_exactly_three_pending_and_valid_audit_chain(self):
        """Verifies FR-29, FR-31, D-073: efter fyllningen väntar exakt 3 godkännanden i kärnans kö, alla i SIM,
        och revisionskedjan är giltig."""
        result = self.seed(days=5)
        self.assertEqual(result.pending, 3)
        self.assertTrue(result.audit_ok)
        config = runtime._load(self.config_dir, console=False)
        with runtime._open(config) as db:
            gov = build_governance(config, db, self.config_dir)
            pending = gov.queue.pending()
            self.assertEqual(len(pending), 3)
            threshold = config.risk.human_approval_threshold.amount_minor
            for request in pending:
                self.assertEqual(request.status, RequestStatus.PENDING)
                self.assertEqual(request.currency, "SIM")
                self.assertGreater(request.amount_minor, threshold)
                self.assertEqual(request.requested_by, "lead-1")
            self.assertTrue(gov.audit.verify().ok)
            actions = [e.action for e in gov.audit.entries()]
            self.assertEqual(actions.count("approval.requested"), 3)
        shutdown_logging()

    def test_refuses_prod(self):
        """Verifies SR-11, ER-15, FR-29: fyllningen vägrar miljön prod och skapar ingen prod-databas."""
        self.edit_system('environment = "sim"', 'environment = "prod"')
        with self.assertRaises(SimulationError) as caught:
            self.seed(days=1)
        self.assertIn("prod", str(caught.exception))
        self.assertFalse((self.dir / "data" / "prod.db").exists())

    def test_refuses_prod_even_with_a_real_currency(self):
        """Verifies SR-11, FR-29: med en giltig prod-konfiguration (SEK) stoppar `require_sim` innan databasen öppnas."""
        self.edit_system('environment = "sim"', 'environment = "prod"')
        self.edit_system('base_currency = "SIM"', 'base_currency = "SEK"')
        path = self.config_dir / "risk_limits.toml"
        text = path.read_text(encoding="utf-8")
        self.assertIn('currency = "SIM"', text)
        path.write_text(text.replace('currency = "SIM"', 'currency = "SEK"'), encoding="utf-8")
        with self.assertRaises(SimulationError) as caught:
            self.seed(days=1)
        self.assertIn("bara i miljön sim", str(caught.exception))
        self.assertFalse((self.dir / "data" / "prod.db").exists())

    def test_refuses_a_database_that_already_has_a_run(self):
        """Verifies D-042, FR-29: en datamapp med en körning fylls inte igen, så kön får aldrig fler än 3."""
        self.seed(days=1)
        with self.assertRaises(SimulationError):
            self.seed(days=1)


class TestScript(SeedCase):
    def test_script_prints_result_and_refuses_prod(self):
        """Verifies FR-29, SR-11: skriptet skriver ut sökvägen och antalet, och avslutar med 1 i prod."""
        script = _load_script()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = script.main(["--config-dir", str(self.config_dir), "--days", "2"])
        shutdown_logging()
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("3 väntande godkännanden", out.getvalue())
        self.assertIn("revisionslogg OK", out.getvalue())
        self.assertIn("sim.db", out.getvalue())
        self.edit_system('environment = "sim"', 'environment = "prod"')
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = script.main(["--config-dir", str(self.config_dir), "--days", "1"])
        shutdown_logging()
        self.assertEqual(code, 1)
        self.assertIn("FEL:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
