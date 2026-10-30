"""Verifies FR-03, SR-09/11: private offline backup and recovery readiness."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from aie.memory.backup import BackupError, create, verify
from .test_pilot_live import PilotLive


class BackupRecovery(PilotLive):
    def snapshot(self):
        self.prepare_and_approve()
        self.system_ = self.system()
        self.system_.db.connection.execute("PRAGMA wal_autocheckpoint = 0")
        self.system_.audit.append("robin", "backup.test", {})
        return create(self.root / "data" / "prod.db", self.root / "backups")

    def test_online_wal_backup_restores_ledger_approvals_and_audit(self):
        snapshot = self.snapshot()
        result = verify(snapshot)
        counts = result["database"]["row_counts"]
        self.assertEqual(result["database"]["environment"], "prod")
        self.assertEqual(counts["ledger_entries"], len(self.system_.ledger.entries()))
        self.assertEqual(counts["approval_requests"], 1)
        self.assertEqual(result["database"]["audit_head"], self.system_.audit.verify().head_hash)
        with sqlite3.connect(snapshot) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='backup.test'").fetchone()[0], 1)
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        self.assertEqual(snapshot.with_suffix(".json").stat().st_mode & 0o777, 0o600)

    def test_rehearsal_never_overwrites_working_database(self):
        snapshot = self.snapshot()
        old = verify(snapshot)["database"]["audit_rows"]
        self.system_.audit.append("robin", "after.backup", {})
        self.assertEqual(verify(snapshot)["database"]["audit_rows"], old)
        self.assertEqual(self.system_.audit.verify().checked, old + 1)
        second = create(self.root / "data" / "prod.db", self.root / "backups")
        self.assertNotEqual(snapshot, second)
        self.assertEqual(verify(second)["database"]["audit_rows"], old + 1)

    def test_modified_snapshot_is_refused(self):
        snapshot = self.snapshot()
        with snapshot.open("ab") as stream:
            stream.write(b"damaged")
        with self.assertRaisesRegex(BackupError, "SHA-256"):
            verify(snapshot)

    def test_rehashed_backup_still_needs_valid_audit(self):
        snapshot = self.snapshot()
        with sqlite3.connect(snapshot) as conn:
            triggers = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'").fetchall()
            for (name,) in triggers:
                conn.execute(f'DROP TRIGGER "{name}"')
            conn.execute("UPDATE audit_log SET action='tampered' WHERE seq=1")
        path = snapshot.with_suffix(".json")
        manifest = json.loads(path.read_text())
        manifest["sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(BackupError, "revisionskedjan"):
            verify(snapshot)

    def test_missing_source_is_not_created(self):
        source = self.dir / "absent.db"
        with self.assertRaises(BackupError):
            create(source, self.dir / "backups")
        self.assertFalse(source.exists())
        self.assertFalse((self.dir / "backups").exists())

    def test_cli_verifies_snapshot(self):
        snapshot = self.snapshot()
        root = Path(__file__).resolve().parents[2]
        process = subprocess.run([sys.executable, "-m", "aie.memory.backup", "verify", str(snapshot)],
            cwd=root, env=dict(os.environ, PYTHONPATH=str(root / "src")), capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("Återställningsövning OK: prod", process.stdout)
