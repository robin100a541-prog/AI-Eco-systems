"""Kapitalbegreppen och den skyddade reserven (Fas 4c, §5, §23, ER-05, ER-10, ER-11).

`capital_position()` räknar de sju begreppen i §23 direkt från ledgern, i en valuta i taget:

| Begrepp (§23)                    | Hur det räknas                                                       |
|----------------------------------|----------------------------------------------------------------------|
| Likvida medel                    | genomförda in- minus utbetalningar: intäkter + insatt kapital − kostnader − avgifter − återbetalningar − uttag |
| Bundet kapital                   | 0. Ledgern har inga tillgångsposter än; en tillgång som inte kan säljas räknas aldrig som likvid (§23) |
| Totalt redovisat kapital         | likvida medel + bundet kapital                                        |
| Skyddad reserv                   | `MINIMUM_RESERVE` i `risk_limits.toml`; ändras bara av grundarna (§5, SR-04) |
| Redan åtagna kostnader           | väntade utgifter (kostnader, avgifter, återbetalningar, uttag med status `pending`) |
| Kapital som får disponeras       | likvida medel − reserven − åtagandena, aldrig under 0                |
| Realiserad vinst som får återinvesteras | 0 tills Tax Engine (4f) kan reservera skatten (ER-19); vinst före skatt är inte disponibel |

En väntad inbetalning räknas aldrig (ER-11). Saknas `MINIMUM_RESERVE` kan inget disponeras (ER-02).
Budgetmotorn blockerar varje utgift som är större än det disponibla kapitalet, så att reserven
aldrig används i normal verksamhet (ER-05, §52 "skyddad reserv respekteras").
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config.models import RiskLimits
from ..ledger import Entry, EntryType, Status

_IN = frozenset({EntryType.REVENUE, EntryType.CAPITAL_IN})
_OUT = frozenset(
    {EntryType.COST, EntryType.FEE, EntryType.REFUND, EntryType.CAPITAL_OUT}
)


@dataclass(frozen=True, slots=True)
class CapitalPosition:
    currency: str
    liquid_minor: int
    bound_minor: int
    total_minor: int
    reserve_minor: int | None  # None = MINIMUM_RESERVE saknas
    committed_minor: int
    disposable_minor: int
    reinvestable_minor: int
    notes: tuple[str, ...]

    def describe(self) -> str:
        reserve = "saknas" if self.reserve_minor is None else str(self.reserve_minor)
        return (
            f"Likvida medel {self.liquid_minor}, bundet {self.bound_minor}, totalt {self.total_minor}, "
            f"skyddad reserv {reserve}, åtaget {self.committed_minor}, disponibelt {self.disposable_minor}, "
            f"återinvesterbart {self.reinvestable_minor} {self.currency}"
        )


def capital_position(entries: tuple[Entry, ...], limits: RiskLimits) -> CapitalPosition:
    currency = limits.currency
    liquid = committed = 0
    for e in entries:
        if e.currency != currency:
            continue  # ER-15: aldrig olika valutor i samma beräkning
        if e.status is Status.SETTLED:
            if e.entry_type in _IN:
                liquid += e.amount_minor
            elif e.entry_type in _OUT:
                liquid -= e.amount_minor
        elif e.status is Status.PENDING and e.entry_type in _OUT:
            committed += e.amount_minor
    notes = ["bundet kapital räknas som 0: ledgern har inga tillgångsposter än"]
    reserve = (
        limits.minimum_reserve.amount_minor
        if limits.minimum_reserve is not None
        else None
    )
    if reserve is None:
        disposable = 0
        notes.append("MINIMUM_RESERVE saknas; inget kapital får disponeras (ER-02)")
    else:
        disposable = max(0, liquid - reserve - committed)
    notes.append(
        "återinvesterbar vinst är 0 tills Tax Engine kan reservera skatten (ER-19, 4f)"
    )
    return CapitalPosition(
        currency, liquid, 0, liquid, reserve, committed, disposable, 0, tuple(notes)
    )
