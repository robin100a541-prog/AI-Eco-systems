"""Agenternas livscykel som tillståndsmaskin (konstitutionen §32–34, FR-06).

PROPOSED → CREATED → TESTING → ACTIVE ⇄ PROBATION
                                 ↓  ↑         ↓
                              SUSPENDED ──────┘
Från alla tillstånd utom RETIRED går det att avveckla (RETIRED). RETIRED är slutgiltigt.

Bara övergångar i `TRANSITIONS` är tillåtna. Allt annat är `IllegalTransition`.
"""
from __future__ import annotations

from enum import Enum


class AgentState(str, Enum):
    PROPOSED = "PROPOSED"  # föreslagen, finns bara på papper
    CREATED = "CREATED"  # skapad, får inte göra något än
    TESTING = "TESTING"  # testas; får bara agera i sim (SR-13)
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"  # under prövning: får agera men följs upp (§33)
    SUSPENDED = "SUSPENDED"  # tillfälligt avstängd: får ingenting
    RETIRED = "RETIRED"  # permanent avvecklad: behörigheter återkallade (SR-14)


S = AgentState
TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    S.PROPOSED: frozenset({S.CREATED, S.RETIRED}),
    S.CREATED: frozenset({S.TESTING, S.RETIRED}),
    S.TESTING: frozenset({S.ACTIVE, S.CREATED, S.RETIRED}),  # CREATED = tillbaka för rättning
    S.ACTIVE: frozenset({S.PROBATION, S.SUSPENDED, S.RETIRED}),
    S.PROBATION: frozenset({S.ACTIVE, S.SUSPENDED, S.RETIRED}),
    S.SUSPENDED: frozenset({S.PROBATION, S.RETIRED}),  # åter via prövning, aldrig direkt till ACTIVE
    S.RETIRED: frozenset(),
}

# Tillstånd där en agent alls får använda verktyg. TESTING begränsas dessutom till sim.
ACTING_STATES = frozenset({S.ACTIVE, S.PROBATION, S.TESTING})


class IllegalTransition(ValueError):
    pass


def check_transition(current: AgentState, target: AgentState) -> None:
    if target not in TRANSITIONS[current]:
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS[current])) or "inga (slutgiltigt)"
        raise IllegalTransition(
            f"{current.value} → {target.value} är inte tillåtet (tillåtna: {allowed})"
        )
