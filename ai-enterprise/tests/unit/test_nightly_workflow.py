"""Tester för den nattliga körningen (PR 9, D-061). Verifierar SR-10, SR-11 och arbetsorder 02 DEL 9.

Arbetsflödet är YAML och kan inte köras lokalt. Testerna läser filen som text, eftersom projektet bara
använder standardbiblioteket, och kontrollerar säkerhetsreglerna.
"""
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "nightly.yml"


def steps(text: str) -> list[str]:
    return re.split(r"\n      - (?=name:|uses:)", text)


class TestNightlyWorkflow(unittest.TestCase):
    def setUp(self):
        if not WORKFLOW.exists():
            self.skipTest("arbetsflödet finns bara i hela repot")
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_nightly_and_by_hand_never_on_pull_requests(self):
        """Verifies D-061: schema och knapp; aldrig pull_request_target eller pull_request (inga hemligheter till forkar)."""
        self.assertIn("schedule:", self.text)
        self.assertIn("workflow_dispatch:", self.text)
        self.assertNotIn("pull_request", self.text)

    def test_only_read_access_except_the_issue_job(self):
        """Verifies D-061: jobbet läser bara; bara felrapporten får skriva ärenden, och inget får skriva kod."""
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertEqual(self.text.count("issues: write"), 1)
        self.assertNotIn("contents: write", self.text)
        self.assertNotIn("pull-requests: write", self.text)

    def test_the_groq_secret_is_only_in_the_groq_step_and_never_in_a_fork(self):
        """Verifies SR-10: GROQ_API_KEY finns bara i ett steg, som kräver huvudrepot och aldrig skriver ut nyckeln."""
        with_secret = [s for s in steps(self.text) if "secrets." in s]
        self.assertEqual(len(with_secret), 1)
        groq = with_secret[0]
        self.assertIn("secrets.GROQ_API_KEY", groq)
        self.assertIn("github.repository == 'robin100a541-prog/AI-Eco-systems'", groq)
        self.assertIn("continue-on-error: true", groq)
        self.assertNotRegex(groq, r"echo[^\n]*\$GROQ_API_KEY")
        self.assertNotIn("BOT_TOKEN", self.text)

    def test_only_sim_and_no_publishing(self):
        """Verifies SR-11: körningen kontrollerar sim med SIM först, och inget publiceras, pushas eller betalas."""
        order = [s.split("\n", 1)[0] for s in steps(self.text)]
        self.assertLess(order.index("name: Bara sim"), order.index("name: Tester"))
        self.assertIn("c.system.environment == 'sim' and c.risk.currency == 'SIM'", self.text)
        for forbidden in ("git push", "gh pr", "gh release", "--agents local", "environment = \"prod\""):
            self.assertNotIn(forbidden, self.text)
        self.assertIn("--agents scripted", self.text)

    def test_failures_open_an_issue_and_reports_are_uploaded(self):
        """Verifies D-061: rapporterna laddas upp även vid fel, och ett fel ger ett ärende."""
        self.assertIn("actions/upload-artifact", self.text)
        self.assertIn("if: always()", self.text)
        self.assertIn("if: failure()", self.text)
        self.assertIn("gh issue create", self.text)
        self.assertIn("shell: bash", self.text)  # pipefail: ett fel före | tee fäller steget
