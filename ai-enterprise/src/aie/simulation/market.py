"""Simulerad marknad och klocka (Fas 6b-1, FR-20, D-042).

`Market.day(day)` räknar fram dagens order per initiativ ur scenariot, utan att röra något:

- Antalet köp är ett binomialutfall: `visitors` försök med sannolikheten `conversion_bp`.
- `demand_shock` skalar sannolikheten med `factor_bp`, och `platform_outage` stoppar all försäljning.
- `cost_spike` skalar `unit_cost`.
- Varje order kan återbetalas med sannolikheten `refund_bp`.
- Avgiften är `fee_fixed + price × fee_bp`, avrundad uppåt till hela enheter.

Slumpen är seedad per scenario, dag och initiativ. Samma scenario ger alltid samma marknad, även efter
en omstart och oavsett i vilken ordning dagarna räknas (`random.Random` med en textseed är
deterministisk mellan körningar).

`SimClock` är den simulerade tiden. Dag 1 är `start_date`. Affärskomponenterna (ledgern, skatten,
prognoserna, stoppen, budgetmotorn) använder den. Revisionsloggen fortsätter med riktig tid.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .scenario import Initiative, Scenario


class SimClock:
    """Simulerad tid. `clock()` ger ISO-text (ledgern m.fl.), `clock.now()` ett datetime (budgetmotorn)."""

    def __init__(self, start_date: str, day: int = 1) -> None:
        self._start = date.fromisoformat(start_date)
        self.day = day

    @property
    def date(self) -> str:
        return (self._start + timedelta(days=self.day - 1)).isoformat()

    def now(self) -> datetime:
        d = self._start + timedelta(days=self.day - 1)
        return datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC)

    def __call__(self) -> str:
        return self.now().isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class Order:
    initiative: str
    number: int  # löpnummer inom dagen och initiativet
    price: int
    fee: int
    unit_cost: int
    refunded: bool


@dataclass(frozen=True, slots=True)
class InitiativeDay:
    initiative: str
    orders: tuple[Order, ...]
    notes: tuple[str, ...]

    @property
    def revenue(self) -> int:
        return sum(o.price for o in self.orders)

    @property
    def refunds(self) -> int:
        return sum(o.price for o in self.orders if o.refunded)

    @property
    def costs(self) -> int:
        return sum(o.fee + o.unit_cost for o in self.orders)


class Market:
    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario

    def day(self, day: int, paused: frozenset[str] = frozenset(),
            unlisted: frozenset[str] = frozenset()) -> tuple[InitiativeDay, ...]:
        """Dagens order per initiativ. `paused`: stoppade av en spärr. `unlisted`: inte listade av agenterna."""
        return tuple(self._initiative_day(day, i, i.key in paused, i.key in unlisted)
                     for i in self._scenario.initiatives)

    def _initiative_day(self, day: int, initiative: Initiative, paused: bool, unlisted: bool = False) -> InitiativeDay:
        notes: list[str] = []
        if unlisted:
            return InitiativeDay(initiative.key, (), ("inte listat till försäljning",))
        if day < initiative.listed_from:
            return InitiativeDay(initiative.key, (), (f"säljer från dag {initiative.listed_from}",))
        if paused:
            return InitiativeDay(initiative.key, (), ("försäljningen är pausad av en spärr",))
        if any(e.kind == "platform_ban" and e.platform == initiative.platform and e.active_on(day)
               for e in self._scenario.events if initiative.platform is not None):
            return InitiativeDay(initiative.key, (), ("plattformen har stängt kontot",))
        events = [e for e in self._scenario.events if e.initiative == initiative.key and e.active_on(day)]
        if any(e.kind == "platform_outage" for e in events):
            return InitiativeDay(initiative.key, (), ("plattformen ligger nere",))
        conversion = initiative.conversion_bp
        unit_cost = initiative.unit_cost
        for e in events:
            if e.kind == "demand_shock":
                conversion = conversion * e.factor_bp // 10_000
                notes.append(f"efterfrågan × {e.factor_bp / 10_000:g}")
            elif e.kind == "cost_spike":
                unit_cost = unit_cost * e.factor_bp // 10_000
                notes.append(f"styckkostnad × {e.factor_bp / 10_000:g}")
        rng = random.Random(f"{self._scenario.seed}:{day}:{initiative.key}")
        sold = sum(1 for _ in range(initiative.visitors) if rng.random() * 10_000 < conversion)
        fee = initiative.fee_fixed + -(-initiative.price * initiative.fee_bp // 10_000)
        orders = tuple(
            Order(initiative.key, n, initiative.price, fee, unit_cost, rng.random() * 10_000 < initiative.refund_bp)
            for n in range(1, sold + 1)
        )
        return InitiativeDay(initiative.key, orders, tuple(notes))
