"""Tester för scripts/check_env.py. Verifierar DR-03, DR-07 och SR-10 (inga hemligheter i utdata)."""
import io
import sys
import unittest
from collections import namedtuple
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_env as ce  # noqa: E402

VI = namedtuple("VI", "major minor micro releaselevel serial")
Usage = namedtuple("Usage", "total used free")


class TestChecks(unittest.TestCase):
    def test_old_python_is_blocking(self):
        """Verifies DR-07: Python < 3.11 blockerar."""
        r = ce.Report("t")
        ce.check_python(r, VI(3, 10, 4, "final", 0))
        self.assertEqual(r.checks[0].status, ce.FAIL)
        self.assertEqual(len(r.blocking_failures), 1)

    def test_new_python_ok(self):
        r = ce.Report("t")
        ce.check_python(r, VI(3, 12, 1, "final", 0))
        self.assertEqual(r.checks[0].status, ce.OK)

    def test_missing_git_is_blocking(self):
        r = ce.Report("t")
        ce.check_git(r, runner=lambda cmd: None)
        self.assertEqual(r.checks[0].status, ce.FAIL)

    def test_api_key_warns_and_never_prints_value(self):
        """Verifies DR-03 och SR-10: varnar för API-fakturering men visar aldrig nyckeln."""
        secret = "sk-ant-THIS-MUST-NOT-LEAK"
        r = ce.Report("t")
        ce.check_api_key(r, environ={"ANTHROPIC_API_KEY": secret})
        self.assertEqual(r.checks[0].status, ce.WARN)
        self.assertNotIn(secret, ce.render_markdown(r))

    def test_no_api_key_ok(self):
        r = ce.Report("t")
        ce.check_api_key(r, environ={})
        self.assertEqual(r.checks[0].status, ce.OK)

    def test_low_disk_warns_not_blocks(self):
        r = ce.Report("t")
        ce.check_disk(r, usage=lambda p: Usage(0, 0, 1 * 1024**3))
        self.assertEqual(r.checks[0].status, ce.WARN)
        self.assertEqual(r.blocking_failures, [])

    def test_ram_unknown_is_info(self):
        r = ce.Report("t")
        ce.check_ram(r, None)
        self.assertEqual(r.checks[0].status, ce.INFO)

    def test_optional_tools_never_block(self):
        r = ce.Report("t")
        ce.check_optional_tools(r, runner=lambda cmd: None)
        self.assertTrue(all(c.status == ce.INFO for c in r.checks))

    def test_markdown_escapes_pipes(self):
        r = ce.Report("t")
        r.add("x", ce.INFO, "a|b")
        self.assertIn("a\\|b", ce.render_markdown(r))


class TestEndToEnd(unittest.TestCase):
    def test_main_runs_on_this_machine(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ce.main(["--founder", "Testare"])
        out = buf.getvalue()
        self.assertIn("## Miljö: Testare", out)
        self.assertIn("Resultat:", out)
        self.assertIn(code, (0, 1))
        self.assertEqual(code == 0, "REDO för Fas 1" in out and "INTE REDO" not in out)


if __name__ == "__main__":
    unittest.main()
