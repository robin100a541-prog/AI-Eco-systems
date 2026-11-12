"""En SIM-databas (Command Center v2 Del 5): scoutens register flyttas till företagets databas utan att något går förlorat."""
import re
import tempfile
import unittest
from pathlib import Path

from aie.config import load_config
from aie.dashboard.export import scout_counts
from aie.governance.cli import build
from aie.memory import Database
from aie.scout.merge import MergeError, merge_register
from aie.scout.register import ScoutRegister
from aie.simulation.agents import ensure_org

from .fixture_config import TEST_CONFIG

REPO = Path(__file__).resolve().parents[3]
COLUMNS = "key, version, type, niche, title, status, data, reason, actor, at"


class MergeCase(unittest.TestCase):
    def open(self, name):
        db = Database.open(Path(self.tmp.name) / name, "sim")
        self.addCleanup(db.close)
        gov = build(load_config(TEST_CONFIG), db, TEST_CONFIG)
        ensure_org(gov.registry, "robin")
        return db, gov

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_db, self.old_gov = self.open("scout")
        self.db, self.gov = self.open("company")
        reg = ScoutRegister(self.old_db, self.old_gov.audit)
        reg.record("scout-1", "a", "pod", "fotboll", "Tröja", "new", {"total": 61}, "ny idé")
        reg.move("scout-1", "a", "scored", "poäng 61/100", qualified=True)
        reg.move("scout-1", "a", "proposed", "väntar på grundare (#7)", request_id=7, decision_id=3)
        reg.record("scout-1", "b", "digital", "planering", "Mall", "new", {}, "ny idé")
        reg.move("scout-1", "b", "stopped", "svag: för liten marknad")
        self.old_db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.source = Path(self.old_db.path) if hasattr(self.old_db, "path") else next(
            (Path(self.tmp.name) / "scout").glob("*.db"))

    def rows(self, db):
        return db.connection.execute(f"SELECT {COLUMNS} FROM scout_entries ORDER BY key, version").fetchall()

    def merge(self):
        return merge_register(self.db, self.gov.audit, self.source, "robin")


class TestMerge(MergeCase):
    def test_every_row_is_copied_unchanged(self):
        """FR-34: varje version i scoutens register finns i företagets databas efter flytten, med samma innehåll."""
        before = [tuple(r) for r in self.rows(self.old_db)]
        summary = self.merge()
        after = [tuple(r) for r in self.rows(self.db)]
        self.assertEqual(summary["copied"], 5)
        self.assertEqual(summary["source_rows"], 5)
        for row in before:
            self.assertIn(row, after)

    def test_second_run_copies_nothing(self):
        """FR-34: flytten kan köras flera gånger; andra gången kopieras inget och inget dubbleras."""
        self.merge()
        count = len(self.rows(self.db))
        summary = self.merge()
        self.assertEqual((summary["copied"], summary["skipped"]), (0, 5))
        self.assertEqual(len(self.rows(self.db)), count)

    def test_conflicting_row_aborts_before_writing(self):
        """FR-34: en rad som redan finns med annat innehåll avbryter flytten, och inget skrivs."""
        ScoutRegister(self.db, self.gov.audit).record("scout-1", "b", "pod", "annat", "Annan", "new", {}, "krock")
        with self.assertRaises(MergeError):
            self.merge()
        self.assertEqual(len(self.rows(self.db)), 1)

    def test_pending_proposal_is_reset_not_linked_to_wrong_request(self):
        """SR-02: ett förslag som väntade i den gamla kön pekar aldrig på en begäran i företagets kö."""
        summary = self.merge()
        self.assertEqual(summary["reset"], ["a"])
        entry = ScoutRegister(self.db, self.gov.audit).get("a")
        self.assertEqual(entry.status, "scored")
        self.assertIsNone(entry.data["request_id"])
        self.assertEqual(entry.data["old_request_id"], 7)
        self.assertEqual(entry.version, 4)

    def test_merge_is_audited_and_chain_holds(self):
        """SR-06: flytten loggas som scout.merged med källfilens SHA-256, och revisionskedjan håller."""
        self.merge()
        actions = [r[0] for r in self.db.connection.execute("SELECT action FROM audit_log").fetchall()]
        self.assertIn("scout.merged", actions)
        self.assertTrue(self.gov.audit.verify().ok)

    def test_missing_source_is_refused(self):
        """FR-34: en källfil som inte finns ger ett tydligt fel, och inget skrivs."""
        with self.assertRaises(MergeError):
            merge_register(self.db, self.gov.audit, Path(self.tmp.name) / "saknas.db", "robin")
        self.assertEqual(self.rows(self.db), [])

    def test_snapshot_counts_come_from_the_company_database(self):
        """FR-34: snapshotens scoutsiffror läses ur företagets databas och visar de flyttade möjligheterna."""
        self.merge()
        self.assertEqual(scout_counts(self.db), {"scored": 1, "stopped": 1})


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = (REPO / ".github" / "workflows" / "scout.yml").read_text(encoding="utf-8")

    def test_scout_uses_the_company_database(self):
        """FR-34: scout-workflowen läser och sparar företagets databas (company-), aldrig en egen."""
        self.assertIn("restore-keys: company-", self.text)
        self.assertIn("state.sh pull company data/sim.db", self.text)
        self.assertIn("state.sh push company data/sim.db", self.text)
        self.assertNotRegex(self.text, r"actions/cache/save@v4[^\n]*\n(?:[^\n]*\n){0,4}?[^\n]*key: scout-")

    def test_scout_never_runs_beside_the_daily_cycle(self):
        """FR-34: scout delar concurrency-grupp med company-daily, eftersom de ändrar samma databas."""
        self.assertRegex(self.text, r"concurrency:\s*\n\s*group: company-daily\s*\n\s*cancel-in-progress: false")

    def test_old_database_is_merged_before_the_cycle(self):
        """FR-34: den gamla scoutdatabasen flyttas in före scoutcykeln och sparas som arkiv i KV."""
        merge, run = self.text.index("aie scout merge"), self.text.index("aie scout run")
        self.assertLess(merge, run)
        self.assertTrue(re.search(r"state\.sh push scout \"\$RUNNER_TEMP/scout-old/sim\.db\"", self.text))


if __name__ == "__main__":
    unittest.main()
