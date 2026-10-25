"""Resultatberäkning från ledgern (Fas 4a, ER-09, ER-11, ER-15, ER-16).

**Metoden (ER-09):** nettovinst = realiserade intäkter − återbetalningar − kostnader − avgifter.
- Bara poster med status `settled` räknas. En väntad betalning är ingen intäkt (ER-11).
- Korrigeringsposter räknas med sin typ och sitt tecken, så att en rättad post får rätt belopp.
- `capital_in` och `capital_out` är kapitalrörelser, varken intäkt eller kostnad.
- `failed` och `cancelled` räknas inte.
- Bara en valuta per beräkning (ER-15). Poster i andra valutor ingår aldrig.

Resultatet märks **preliminärt** (ER-11) när något i urvalet fortfarande väntar (`pending`), eller
när ett initiativ har realiserade intäkter men inga kostnader eller avgifter alls ("kostnader saknas").
Poster som skett utan godkännande (`unapproved`) listas som avvikelser.

**Granskning (ER-16):** `recompute` räknar om samma siffror direkt med SQL mot tabellerna, utan
`compute_result`. Audit-agenten jämför med det som rapporterats och får en lista med avvikelser.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..authorization import AuthorizationEngine
from ..memory import Database
from .ledger import Approval, Entry, EntryType, Ledger, Status

AUDIT_TOOL = "audit.verify"
_PNL_TYPES = (EntryType.REVENUE, EntryType.REFUND, EntryType.COST, EntryType.FEE)


@dataclass(frozen=True, slots=True)
class Result:
    currency: str
    initiative: str | None
    department: str | None
    revenue_minor: int
    refunds_minor: int
    costs_minor: int
    fees_minor: int
    net_minor: int
    preliminary: bool
    reasons: tuple[str, ...]
    entry_ids: tuple[int, ...]  # underlaget: exakt vilka poster som räknades
    unapproved: tuple[int, ...]

    def describe(self) -> str:
        scope = (
            ", ".join(x for x in (self.initiative, self.department) if x)
            or "hela företaget"
        )
        mark = (
            " (PRELIMINÄRT: " + "; ".join(self.reasons) + ")"
            if self.preliminary
            else ""
        )
        return f"Nettovinst {scope}: {self.net_minor} {self.currency}{mark}"


def compute_result(
    entries: tuple[Entry, ...],
    currency: str,
    initiative: str | None = None,
    department: str | None = None,
) -> Result:
    scope = [
        e
        for e in entries
        if e.currency == currency
        and (initiative is None or e.initiative == initiative)
        and (department is None or e.department == department)
    ]
    totals = {t: 0 for t in _PNL_TYPES}
    counted: list[int] = []
    for e in scope:
        if e.entry_type in totals and e.status is Status.SETTLED:
            totals[e.entry_type] += e.amount_minor
            counted.append(e.entry_id)
    reasons: list[str] = []
    pending = [
        e.entry_id
        for e in scope
        if e.status is Status.PENDING and e.entry_type in totals
    ]
    if pending:
        reasons.append(f"{len(pending)} poster väntar fortfarande")
    by_initiative: dict[str, set[EntryType]] = {}
    for e in scope:
        if e.status is Status.SETTLED:
            by_initiative.setdefault(e.initiative, set()).add(e.entry_type)
    for name, kinds in sorted(by_initiative.items()):
        if EntryType.REVENUE in kinds and not kinds & {EntryType.COST, EntryType.FEE}:
            reasons.append(f"kostnader saknas för {name}")
    net = (
        totals[EntryType.REVENUE]
        - totals[EntryType.REFUND]
        - totals[EntryType.COST]
        - totals[EntryType.FEE]
    )
    return Result(
        currency,
        initiative,
        department,
        totals[EntryType.REVENUE],
        totals[EntryType.REFUND],
        totals[EntryType.COST],
        totals[EntryType.FEE],
        net,
        bool(reasons),
        tuple(reasons),
        tuple(counted),
        tuple(e.entry_id for e in scope if e.approval is Approval.UNAPPROVED),
    )


def result_for(
    ledger: Ledger,
    actor: str,
    currency: str,
    initiative: str | None = None,
    department: str | None = None,
) -> Result:
    """Som `compute_result`, men bara för den som får läsa ledgern (grundare eller `ledger.read`)."""
    ledger.require_reader(actor)
    return compute_result(ledger.entries(currency), currency, initiative, department)


_RECOMPUTE_SQL = """
WITH latest AS (
    SELECT s.entry_id, s.status FROM ledger_status s
    WHERE s.id = (SELECT MAX(id) FROM ledger_status WHERE entry_id = s.entry_id)
)
SELECT e.entry_type, COALESCE(SUM(e.amount_minor), 0), COUNT(*)
FROM ledger_entries e JOIN latest l ON l.entry_id = e.entry_id
WHERE l.status = 'settled' AND e.currency = ?
  AND (? IS NULL OR e.initiative = ?) AND (? IS NULL OR e.department = ?)
  AND e.entry_type IN ('revenue', 'refund', 'cost', 'fee')
GROUP BY e.entry_type
"""


def recompute(
    db: Database,
    engine: AuthorizationEngine,
    founders: frozenset[str],
    actor: str,
    reported: Result,
) -> tuple[str, ...]:
    """ER-16: räknar om `reported` direkt från tabellerna. Tom tuple betyder att allt stämmer."""
    if actor not in founders:
        engine.require(actor, AUDIT_TOOL)
    i, d = reported.initiative, reported.department
    sums = {t: 0 for t in ("revenue", "refund", "cost", "fee")}
    count = 0
    for kind, total, n in db.connection.execute(
        _RECOMPUTE_SQL, (reported.currency, i, i, d, d)
    ):
        sums[kind] = total
        count += n
    expected = {
        "intäkter": (reported.revenue_minor, sums["revenue"]),
        "återbetalningar": (reported.refunds_minor, sums["refund"]),
        "kostnader": (reported.costs_minor, sums["cost"]),
        "avgifter": (reported.fees_minor, sums["fee"]),
        "nettovinst": (
            reported.net_minor,
            sums["revenue"] - sums["refund"] - sums["cost"] - sums["fee"],
        ),
        "antal poster": (len(reported.entry_ids), count),
    }
    return tuple(
        f"{name}: rapporterat {got}, ledgern visar {real}"
        for name, (got, real) in expected.items()
        if got != real
    )
