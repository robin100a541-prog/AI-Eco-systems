"""Övervakning (FR-24, §16, D-046): loopar, upprepat arbete och kostnad utan värde.

Allt läses ur revisionsloggen och ledgern; inget lagras, så resultatet går alltid att räkna om.

- **Loop:** samma agent gör samma sak (åtgärd och detaljer) `LOOP_REPEATS` gånger i rad.
- **Upprepat arbete:** samma åtgärd med samma detaljer görs `REPEAT_COUNT` gånger eller fler totalt
  av någon agent, utan att vara en loop.
- **Kostnad utan värde:** ett initiativ har kostnader men ingen intäkt, eller en agent gör många
  modellanrop men inget annat.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from ..ledger import EntryType, Status

LOOP_REPEATS = 5
REPEAT_COUNT = 3
LLM_ONLY_CALLS = 10
_SYSTEM_ACTORS = (
    "system",
    "cli",
    "llm",
    "audit",
)  # bokföring av själva systemet, inte arbete
_NOISE = (
    "llm.call",
    "tool.allowed",
    "tool.denied",
)  # följer av annat arbete; räknas inte som arbete


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str  # loop, repeated_work, cost_without_value
    subject: str  # agent eller initiativ
    detail: str


def _key(entry) -> str:
    return f"{entry.action} {json.dumps(entry.details, sort_keys=True, ensure_ascii=False)}"


def monitor(system, since: str = "") -> tuple[Finding, ...]:
    """Fynd från `since` (ISO-tid; tom = hela historiken)."""
    entries = [
        e
        for e in system.audit.entries()
        if e.timestamp >= since and not e.actor.startswith(_SYSTEM_ACTORS)
    ]
    findings: list[Finding] = []
    looped: set[tuple[str, str]] = set()
    by_actor: dict[str, list] = {}
    for e in entries:
        by_actor.setdefault(e.actor, []).append(e)
    for actor, mine in by_actor.items():
        work = [e for e in mine if e.action not in _NOISE]
        run, last = 0, None
        for e in work:
            key = _key(e)
            run = run + 1 if key == last else 1
            last = key
            if run == LOOP_REPEATS:
                looped.add((actor, key))
                findings.append(
                    Finding("loop", actor, f"{e.action} {LOOP_REPEATS} gånger i rad")
                )
        counts = Counter(_key(e) for e in work)
        for key, n in counts.items():
            if n >= REPEAT_COUNT and (actor, key) not in looped:
                findings.append(
                    Finding(
                        "repeated_work",
                        actor,
                        f"{key.split(' ')[0]} {n} gånger med samma underlag",
                    )
                )
        calls = sum(1 for e in mine if e.action == "llm.call")
        if calls >= LLM_ONLY_CALLS and not work:
            findings.append(
                Finding(
                    "cost_without_value",
                    actor,
                    f"{calls} modellanrop utan någon annan åtgärd",
                )
            )
    findings += _initiatives_without_value(system, since)
    return tuple(findings)


def _initiatives_without_value(system, since: str) -> list[Finding]:
    costs: Counter = Counter()
    revenue: Counter = Counter()
    for e in system.ledger.entries(system.currency):
        if e.recorded_at < since or e.status is not Status.SETTLED or not e.initiative:
            continue
        if e.entry_type in (EntryType.COST, EntryType.FEE):
            costs[e.initiative] += e.amount_minor
        elif e.entry_type is EntryType.REVENUE:
            revenue[e.initiative] += e.amount_minor
    return [
        Finding(
            "cost_without_value",
            initiative,
            f"kostnader {amount} {system.currency} och ingen intäkt",
        )
        for initiative, amount in sorted(costs.items())
        if amount > 0 and revenue[initiative] == 0
    ]
