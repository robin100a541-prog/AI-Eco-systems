"""Hashkedjad audit-logg (Fas 1.5, SR-09). Registrerar beslut, verktygsanrop och ändringar.

Två skydd som kompletterar varandra:
1. **Append-only i databasen.** Triggers i migration 2 gör att SQLite vägrar UPDATE och
   DELETE på `audit_log`. Det stoppar misstag och felaktig kod.
2. **Hashkedja.** Varje rad innehåller hashen av föregående rad, och dess egen hash räknas
   över alla fält plus den hashen. Den som går förbi triggers, till exempel med direkt
   åtkomst till filen, kan ändra en rad, men `verify()` hittar då första trasiga raden.

Känd begränsning: om de *sista* raderna tas bort är resten av kedjan fortfarande giltig.
Det upptäcks först när kedjans senaste hash (`Verification.head_hash`) jämförs med en
kopia som sparats någon annanstans. Den jämförelsen är inte byggd än.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config.loader import is_secret_key
from ..memory import Database

GENESIS_HASH = "0" * 64  # "föregående hash" för den första raden


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical(value: Any) -> str:
    """Samma data ger alltid exakt samma text. Annars går hashen inte att räkna om."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    timestamp: str
    actor: str  # agent eller systemkomponent, t.ex. "cli" eller "agent:cfo"
    action: str  # vad som hände, t.ex. "config.loaded"
    details: Mapping[str, Any]
    prev_hash: str
    hash: str

    def expected_hash(self) -> str:
        return _compute_hash(self.seq, self.timestamp, self.actor, self.action, self.details, self.prev_hash)


def _compute_hash(
    seq: int, timestamp: str, actor: str, action: str, details: Mapping[str, Any], prev_hash: str
) -> str:
    payload = {
        "seq": seq,
        "timestamp": timestamp,
        "actor": actor,
        "action": action,
        "details": details,
        "prev_hash": prev_hash,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Verification:
    ok: bool
    checked: int  # antal rader som kontrollerades
    first_bad_seq: int | None = None
    reason: str | None = None
    head_hash: str = GENESIS_HASH  # senaste godkända hash; spara den externt för att upptäcka trunkering


class AuditLog:
    def __init__(self, db: Database, clock: Callable[[], str] = _utc_now) -> None:
        self._db = db
        self._clock = clock

    def append(self, actor: str, action: str, details: Mapping[str, Any] | None = None) -> AuditEntry:
        """Lägger till en rad. Kastar `ValueError`/`TypeError` innan något skrivs om indata är fel."""
        if not actor or not action:
            raise ValueError("actor och action måste anges")
        details = dict(details or {})
        _reject_secrets(details)
        _canonical(details)  # TypeError/ValueError här, inte mitt i transaktionen

        with self._db.transaction() as tx:  # BEGIN IMMEDIATE: två skrivare kan inte få samma seq
            last = tx.execute("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev_hash = (last[0] + 1, last[1]) if last else (1, GENESIS_HASH)
            timestamp = self._clock()
            entry = AuditEntry(
                seq, timestamp, actor, action, details, prev_hash,
                hash=_compute_hash(seq, timestamp, actor, action, details, prev_hash),
            )
            tx.execute(
                "INSERT INTO audit_log (seq, timestamp, actor, action, details, prev_hash, hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entry.seq, entry.timestamp, entry.actor, entry.action,
                 _canonical(entry.details), entry.prev_hash, entry.hash),
            )
        return entry

    def entries(self) -> Iterator[AuditEntry]:
        rows = self._db.connection.execute(
            "SELECT seq, timestamp, actor, action, details, prev_hash, hash FROM audit_log ORDER BY seq"
        )
        for seq, timestamp, actor, action, details, prev_hash, hash_ in rows:
            yield AuditEntry(seq, timestamp, actor, action, json.loads(details), prev_hash, hash_)

    def verify(self) -> Verification:
        """Går igenom hela kedjan och stannar vid första felet."""
        expected_seq, prev_hash, checked = 1, GENESIS_HASH, 0
        try:
            for entry in self.entries():
                problem = None
                if entry.seq != expected_seq:
                    problem = f"rad {expected_seq} saknas (nästa rad är {entry.seq})"
                elif entry.prev_hash != prev_hash:
                    problem = "prev_hash matchar inte föregående rad"
                elif entry.hash != entry.expected_hash():
                    problem = "innehållet har ändrats (hashen stämmer inte)"
                if problem:
                    return Verification(False, checked, entry.seq, problem, prev_hash)
                checked += 1
                expected_seq, prev_hash = entry.seq + 1, entry.hash
        except json.JSONDecodeError:
            return Verification(False, checked, expected_seq, "details är inte giltig JSON", prev_hash)
        return Verification(True, checked, head_hash=prev_hash)


def _reject_secrets(data: Any, path: str = "details") -> None:
    """Audit-loggen kan aldrig rensas i efterhand, så hemligheter får inte ens komma in (SR-10)."""
    if isinstance(data, Mapping):
        for key, value in data.items():
            if is_secret_key(str(key)):
                raise ValueError(f"{path}.{key} ser ut som en hemlighet och loggas aldrig (SR-10)")
            _reject_secrets(value, f"{path}.{key}")
    elif isinstance(data, (list, tuple)):
        for i, item in enumerate(data):
            _reject_secrets(item, f"{path}[{i}]")
