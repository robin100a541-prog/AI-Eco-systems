"""Verifies TEST-001. Test that `main()` returns exit code 0 for a valid configuration when called with the `check-config` command."""
import unittest
from pathlib import Path

from aie.__main__ import _check_config, main
from aie.monitoring import shutdown_logging

ROOT = Path(__file__).resolve().parents[2]


class TestMain(unittest.TestCase):
    def test_check_config_success(self):
        """Verifies TEST-001: `main(['check-config'])` should exit with code 0 for a valid config."""
        exit_code = main(['check-config'])
        self.assertEqual(exit_code, 0)

    def test_check_config_function_returns_zero(self):
        """Verifies FR-02 (BL-013): `_check_config` med repots giltiga config returnerar 0."""
        self.addCleanup(shutdown_logging)
        self.assertEqual(_check_config(ROOT / "config"), 0)


if __name__ == "__main__":
    unittest.main()
