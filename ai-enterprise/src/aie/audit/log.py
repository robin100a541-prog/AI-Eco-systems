"""Hashkedjad revisionslogg (Fas 1.5, SR-09).

Varje rad i tabellen `audit_log` (migration 2) har en hash av sitt eget innehåll och av
föregående rads hash. Den första raden bygger på `GENESIS_HASH`. Därför syns det vid
`verify()` om någon i efterhand ändrar, raderar eller skjuter in en rad.

Två skydd samverkar:
1. SQLite-triggrar vägrar `UPDATE` och `DELETE` på tabellen (append-only).
2. Hashkedjan avslöjar ändringar som ändå görs utanför programmet, till exempel med en
   annan SQLite-klient som först tar bort triggrarna.

Begränsning: den som skriver om den **sista** raden och räknar om dess hash kan inte
upptäckas av kedjan ensam. Det kräver att den senaste hashen sparas någon annanstans
(till exempel i en commit eller ett utskick); det hör till en senare fas.

Detaljer maskeras med samma regler som loggningen innan de sparas (SR-10).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..memory import Database
from ..monitoring import get_logger, mask_fields

GENESIS_HASH = "0" * 64

log = get_logger("audit")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    ts: str
    actor: str
    action: str
    details: dict[str, Any]
    prev_hash: str
    hash: str


def _canonical_details(details: dict[str, Any] | None) -> str:
    """Samma innehåll ger alltid samma text, oavsett nyckelordning."""
    return json.dumps(
        mask_fields(details or {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def entry_hash(
    seq: int, ts: str, actor: str, action: str, details: str, prev_hash: str
) -> str:
    """SHA-256 över radens fält och föregående hash. `details` är den sparade JSON-texten."""
    payload = json.dumps(
        [seq, ts, actor, action, details, prev_hash],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLog:
    """Revisionsloggen i en öppen `Database`."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self, actor: str, action: str, details: dict[str, Any] | None = None
    ) -> AuditEntry:
        """Lägger till en rad i en egen transaktion och returnerar den."""
        with self.db.transaction() as tx:
            return self.record(tx, actor, action, details)

    def record(
        self,
        tx: sqlite3.Connection,
        actor: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Lägger till en rad inom en transaktion som anroparen redan har öppnat.

        Används när en ändring och dess revisionsrad ska sparas tillsammans eller inte alls.
        """
        if not actor or not action:
            raise ValueError("actor och action måste anges i revisionsloggen")
        last = tx.execute(
            "SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        seq, prev_hash = (last[0] + 1, last[1]) if last else (1, GENESIS_HASH)
        ts = datetime.now(UTC).isoformat(timespec="microseconds")
        text = _canonical_details(details)
        digest = entry_hash(seq, ts, actor, action, text, prev_hash)
        tx.execute(
            "INSERT INTO audit_log (seq, ts, actor, action, details, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (seq, ts, actor, action, text, prev_hash, digest),
        )
        log.debug("revisionsrad %d: %s %s", seq, actor, action)
        return AuditEntry(seq, ts, actor, action, json.loads(text), prev_hash, digest)

    def entries(self) -> list[AuditEntry]:
        rows = self.db.connection.execute(
            "SELECT seq, ts, actor, action, details, prev_hash, hash FROM audit_log ORDER BY seq"
        )
        return [
            AuditEntry(seq, ts, actor, action, json.loads(details), prev, digest)
            for seq, ts, actor, action, details, prev, digest in rows
        ]

    def verify(self) -> list[str]:
        """Kontrollerar hela kedjan. Returnerar en lista med problem; tom lista = intakt."""
        problems: list[str] = []
        expected_seq, expected_prev = 1, GENESIS_HASH
        rows = self.db.connection.execute(
            "SELECT seq, ts, actor, action, details, prev_hash, hash FROM audit_log ORDER BY seq"
        )
        for seq, ts, actor, action, details, prev_hash, digest in rows:
            if seq != expected_seq:
                problems.append(
                    f"rad {seq}: förväntade rad {expected_seq} (rad saknas eller har lagts till)"
                )
            if prev_hash != expected_prev:
                problems.append(f"rad {seq}: prev_hash stämmer inte med föregående rad")
            if entry_hash(seq, ts, actor, action, details, prev_hash) != digest:
                problems.append(
                    f"rad {seq}: innehållet har ändrats (hash stämmer inte)"
                )
            expected_seq, expected_prev = seq + 1, digest
        for problem in problems:
            log.error("revisionsloggen är manipulerad: %s", problem)
        return problems
