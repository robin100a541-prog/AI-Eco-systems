"""Utvecklaragentens säkerhet: tak för merges per dygn och veckosammanfattning (Fas 8)."""
import tempfile
import unittest
from pathlib import Path

from aie.dev_agent.safety import MAX_MERGES_PER_DAY, may_merge, merges_today, weekly_summary


def pr(ref, merged_at):
    return {"head": {"ref": ref}, "merged_at": merged_at}


class TestSafety(unittest.TestCase):
    def test_at_most_four_merges_a_day(self):
        prs = [pr(f"claude/dev-agent-2026110{i}", "2026-11-05T10:00:00Z") for i in range(MAX_MERGES_PER_DAY)]
        prs += [pr("claude/other", "2026-11-05T11:00:00Z"), pr("claude/dev-agent-x", "2026-11-04T23:00:00Z"),
                pr("claude/dev-agent-y", None)]
        self.assertEqual(merges_today(prs, "2026-11-05"), 4)
        self.assertFalse(may_merge(prs, "2026-11-05"))
        self.assertTrue(may_merge(prs[1:], "2026-11-05"))

    def test_weekly_summary_counts_runs_items_and_red_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "dev-agent-2026-11-02-0100.md").write_text(
                "# x\n\n## Gjort\n- BL-001 fixa Klart när: `grep a b`\n\n## Tester\n`Ran 5 tests` OK\n")
            (d / "dev-agent-2026-11-03-0100.md").write_text("# y\n\n## Tester\n`Ran 5 tests` FAILED\n")
            (d / "dev-agent-2026-11-10-0100.md").write_text("# annan vecka\n")
            text = weekly_summary(d, 2026, 45)
        self.assertIn("Körningar: 2", text)
        self.assertIn("Klara punkter: 1", text)
        self.assertIn("inte var gröna: 1", text)
        self.assertIn("- BL-001 fixa", text)


if __name__ == "__main__":
    unittest.main()
