"""Consistent SQLite backups and restore rehearsals; never restore over a working DB.

Run from ai-enterprise: PYTHONPATH=src python -m aie.memory.backup create
  data-pilot/data/prod.db --out data-pilot/backups
Then: python -m aie.memory.backup verify <backup.db>

The manifest must be kept with its snapshot. It detects accidental damage, not an
attacker able to replace both files. Keep an additional private off-device copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .database import Database
from .migrations import MIGRATIONS


class BackupError(ValueError):
    pass


def _readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise BackupError("databasfilen finns inte")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _inspect(path: Path) -> dict:
    from ..audit import AuditLog

    with closing(_readonly(path)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("SQLite integrity_check misslyckades")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupError("databasen har brutna främmande nycklar")
        environment = dict(conn.execute("SELECT key, value FROM metadata")).get("environment")
        if environment not in ("sim", "prod"):
            raise BackupError("miljömärkningen saknas eller är ogiltig")
        versions = conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY version").fetchall()
        expected = [(m.version, m.checksum) for m in MIGRATIONS[:len(versions)]]
        if not versions or versions != expected:
            raise BackupError("schemaversion/kontrollsummor stämmer inte med denna kodversion")
        audit = AuditLog(Database(conn, path, environment)).verify()
        if not audit.ok:
            raise BackupError("revisionskedjan är trasig")
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                           "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if not all(re.fullmatch(r"[a-z_]+", table) for table in tables):
            raise BackupError("oväntat tabellnamn")
        counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        return {"environment": environment, "schema_version": versions[-1][0], "row_counts": counts,
                "audit_head": audit.head_hash, "audit_rows": audit.checked}


def verify(snapshot: Path | str) -> dict:
    """Verify hash and restore to a new temporary folder for an independent read check."""
    snapshot = Path(snapshot)
    try:
        manifest = json.loads(snapshot.with_suffix(".json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format") != 1 or not isinstance(manifest.get("database"), dict):
            raise BackupError("okänt eller ogiltigt backupmanifest")
        if manifest.get("sha256") != _digest(snapshot):
            raise BackupError("backupens SHA-256 stämmer inte med manifestet")
        expected = manifest["database"]
        with tempfile.TemporaryDirectory(prefix="aie-restore-") as folder:
            restored = Path(folder) / "restored.db"
            # Backup API also exercises recovery of the snapshot, without touching the source.
            with closing(_readonly(snapshot)) as source, closing(sqlite3.connect(restored)) as dest:
                source.backup(dest)
            actual = _inspect(restored)
            if actual != expected:
                raise BackupError("återställda tabellantal, schema eller revisionskedja avviker")
        return manifest
    except (OSError, sqlite3.Error, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"backupen kunde inte verifieras ({type(exc).__name__})") from exc


def create(database: Path | str, out: Path | str) -> Path:
    """Online snapshot includes WAL contents; existing databases/backups are never overwritten."""
    database, out = Path(database), Path(out)
    if not database.is_file():
        raise BackupError("databasen finns inte; ingen tom databas skapas")
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = out / f"{database.stem}-{stamp}-{uuid4().hex[:8]}.db"
    fd, temporary = tempfile.mkstemp(prefix=".snapshot-", suffix=".db", dir=out)
    os.close(fd)
    tmp = Path(temporary)
    try:
        with closing(_readonly(database)) as source, closing(sqlite3.connect(tmp)) as dest:
            source.backup(dest)
        details = _inspect(tmp)
        manifest = {"format": 1, "created_at": datetime.now(UTC).isoformat(),
                    "database": details, "sha256": _digest(tmp)}
        # Exclusive destination creation keeps even an improbable name collision harmless.
        with snapshot.open("xb") as stream, tmp.open("rb") as source:
            os.chmod(snapshot, 0o600)
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        manifest_path = snapshot.with_suffix(".json")
        with manifest_path.open("x", encoding="utf-8") as stream:
            os.chmod(manifest_path, 0o600)
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        verify(snapshot)
        return snapshot
    except (OSError, sqlite3.Error) as exc:
        raise BackupError(f"backupen kunde inte skapas ({type(exc).__name__})") from exc
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Privat SQLite-backup och säker återställningsövning")
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("create")
    save.add_argument("database", type=Path)
    save.add_argument("--out", type=Path, default=Path("data-pilot/backups"))
    check = commands.add_parser("verify")
    check.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "create":
            path = create(args.database, args.out)
            print(f"Backup och återställningsövning OK: {path}")
        else:
            result = verify(args.snapshot)
            print(f"Återställningsövning OK: {result['database']['environment']}, "
                  f"schema {result['database']['schema_version']}, "
                  f"{result['database']['audit_rows']} revisionsposter")
        return 0
    except BackupError as exc:
        parser.exit(1, f"FEL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
