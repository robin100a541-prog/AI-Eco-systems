"""Tester för den dagliga Printify-körningen (arbetsorder 04, D-065). Verifierar SR-10: hemligheten når aldrig
en fork och skrivs aldrig ut. Arbetsflödet läses som text, eftersom projektet bara använder standardbiblioteket."""
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "printify-catalog.yml"


class TestPrintifyWorkflow(unittest.TestCase):
    def setUp(self):
        if not WORKFLOW.exists():
            self.skipTest("arbetsflödet finns bara i hela repot")
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_never_runs_for_pull_requests_and_only_in_the_main_repo(self):
        """Verifies SR-10: schema och knapp, aldrig pull_request; bara huvudrepot."""
        self.assertIn("schedule:", self.text)
        self.assertIn("workflow_dispatch:", self.text)
        triggers = self.text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertNotIn("pull_request", triggers)
        self.assertIn("github.repository == 'robin100a541-prog/AI-Eco-systems'", self.text)

    def test_the_secret_is_only_in_the_read_step_and_is_never_echoed(self):
        """Verifies SR-10 och D-069: nyckeln i ett steg, aldrig utskriven; bara läsning, inga skrivrättigheter."""
        steps = re.split(r"\n      - (?=name:|uses:)", self.text)
        with_secret = [s for s in steps if "secrets." in s]
        self.assertEqual(len(with_secret), 1)
        self.assertIn("name: Läs katalogen", with_secret[0])
        self.assertNotRegex(self.text, r"echo[^\n]*\$PRINTIFY_API_TOKEN")
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotIn("write", self.text.split("jobs:")[0])
        for forbidden in ("printify.draft", "publish", "git push", "gh pr"):
            self.assertNotIn(forbidden, self.text.replace("Utkast (`printify.draft`)", "").replace("kan aldrig publicera", ""))
        self.assertIn("shell: bash", self.text)
