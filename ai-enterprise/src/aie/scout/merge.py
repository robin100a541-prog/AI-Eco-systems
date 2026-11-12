"""`py -m aie scout merge --from <fil>`: flyttar scoutens register till företagets databas (en enda sanning).

Scouten hade en egen SIM-databas (cacheprefixet `scout-`). Registret `scout_entries` kopieras rad för rad, med
samma nyckel, version, tid och aktör. Inget skrivs om och inget raderas:

- Finns raden redan med samma innehåll hoppas den över, så kommandot kan köras flera gånger.
- Finns raden med annat innehåll avbryts allt innan något skrivs.
- Ett förslag som väntade på en grundare i den gamla databasen pekar på en begäran som bara fanns där. Det
  flyttas tillbaka till `scored` med den gamla begärans nummer sparat, så att scouten föreslår det på nytt här
  och numret aldrig blandas ihop med en begäran i företagets kö.

Den gamla databasens revisionslogg flyttas inte: den är en egen hashkedja och kan inte vävas in i företagets
utan att skriva om historik. Den gamla filen sparas oförändrad som `state:scout` i KV. Flytten själv loggas
som `scout.merged` i företagets revisionslogg, med källfilens SHA-256.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from .register import ScoutRegister

COLUMNS = "key, version, type, niche, title, status, data, reason, actor, at"


class MergeError(ValueError):
    """Flytten avbröts; inget skrevs."""


def _source_rows(source: Path) -> list[tuple]:
    con = sqlite3.connect(f"{Path(source).resolve().as_uri()}?mode=ro", uri=True)
    try:
        has = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'scout_entries'").fetchone()
        return con.execute(f"SELECT {COLUMNS} FROM scout_entries ORDER BY key, version").fetchall() if has else []
    finally:
        con.close()


def merge_register(db, audit, source: Path, actor: str) -> dict:
    """Kopierar källans register till `db`. Returnerar antal kopierade, överhoppade och omställda förslag."""
    source = Path(source)
    if not source.is_file():
        raise MergeError(f"källfilen {source} finns inte")
    rows = _source_rows(source)
    existing = {(r[0], r[1]): tuple(r) for r in
                db.connection.execute(f"SELECT {COLUMNS} FROM scout_entries").fetchall()}
    new = []
    for row in rows:
        row = tuple(row)
        have = existing.get((row[0], row[1]))
        if have is None:
            new.append(row)
        elif have != row:
            raise MergeError(f"{row[0]} version {row[1]} finns redan med annat innehåll; inget flyttades")
    with db.transaction() as tx:
        tx.executemany(f"INSERT INTO scout_entries ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", new)
    summary = {"copied": len(new), "skipped": len(rows) - len(new), "source_rows": len(rows),
               "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    reg = ScoutRegister(db, audit)
    reset = []
    for key in sorted({row[0] for row in new}):
        entry = reg.get(key)
        rid = entry.data.get("request_id")
        if entry.status == "proposed" and rid is not None:
            reg.move(actor, key, "scored",
                     f"flyttad från scoutens gamla databas: begäran #{rid} fanns bara där; föreslås på nytt",
                     request_id=None, decision_id=None, old_request_id=rid,
                     old_decision_id=entry.data.get("decision_id"))
            reset.append(key)
    summary["reset"] = reset
    if new:
        audit.append(actor, "scout.merged", {k: summary[k] for k in ("copied", "skipped", "source_rows", "source_sha256")}
                     | {"reset": len(reset)})
    missing = [r for r in rows if db.connection.execute(
        "SELECT 1 FROM scout_entries WHERE key = ? AND version = ?", (r[0], r[1])).fetchone() is None]
    if missing:
        raise MergeError(f"{len(missing)} rader saknas efter flytten")
    return summary


def main(config_dir: Path, founder: str, source: Path | None) -> int:
    from .. import runtime
    from ..governance.cli import build

    if source is None:
        print("FEL: ange källan med --from <databasfil>", file=sys.stderr)
        return 1
    config = runtime._load(config_dir, console=False)
    with runtime._open(config) as db:
        gov = build(config, db, config_dir)
        try:
            summary = merge_register(db, gov.audit, source, founder)
        except (MergeError, sqlite3.Error) as exc:
            print(f"FEL: {exc}", file=sys.stderr)
            return 1
    print("scout merge: " + json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in summary.items()
                                        if k != "source_sha256"}, ensure_ascii=False))
    return 0
