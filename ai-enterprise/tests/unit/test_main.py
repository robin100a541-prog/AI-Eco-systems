"""Verifies TEST-001. Test that `main()` returns exit code 0 for a valid configuration when called with the `check-config` command."""
import unittest

from aie.__main__ import main


class TestMain(unittest.TestCase):
    def test_check_config_success(self):
        """Verifies TEST-001: `main(['check-config'])` should exit with code 0 for a valid config."""
        exit_code = main(['check-config'])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
