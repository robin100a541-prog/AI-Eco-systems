"""Periodisk företagsrapport (FR-22, konstitutionen §58, D-046).

`periodic_report(system, start, end)` analyserar perioden `[start, end]` (datum, `ÅÅÅÅ-MM-DD`) med de
tio punkterna i §58. Allt räknas ur ledgern, prognosloggen, lärdomsregistret och övervakningen.

För jämförelser mellan perioder och initiativ har varje initiativ samma nyckeltal (`InitiativeFigures`):
nettovinst, marginal, avkastning på insatt kostnad, nettovinst per dag och största dagsförlust. Det tar
hänsyn till skillnader i kapital (avkastning), tidsåtgång (per dag) och risk (största dagsförlust), §58.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from ..budget.capital import capital_position
from ..ledger import EntryType, Status, compute_result
from .monitor import monitor

POINTS = (
    "Kapitalutveckling",
    "Nettovinst",
    "Kassaflöde",
    "Utveckling per departement",
    "Resultat per affärsinitiativ",
    "Prognosprecision",
    "Kostnadseffektivitet",
    "Riskexponering",
    "Lärdomar",
    "Rekommenderade förändringar",
)
_IN = (EntryType.REVENUE, EntryType.CAPITAL_IN)
_OUT = (
    EntryType.COST,
    EntryType.FEE,
    EntryType.REFUND,
    EntryType.CAPITAL_OUT,
    EntryType.TAX_PAYMENT,
)


@dataclass(frozen=True, slots=True)
class InitiativeFigures:
    initiative: str
    revenue_minor: int
    costs_minor: int  # kostnader + avgifter + återbetalningar
    net_minor: int
    days_active: int
    worst_day_minor: int  # största förlust under en dag (0 = ingen förlustdag)

    @property
    def margin_percent(self) -> float | None:
        return (
            None
            if self.revenue_minor == 0
            else 100 * self.net_minor / self.revenue_minor
        )

    @property
    def return_percent(self) -> float | None:
        """Avkastning på insatt kostnad: jämför initiativ med olika mycket kapital."""
        return (
            None if self.costs_minor == 0 else 100 * self.net_minor / self.costs_minor
        )

    @property
    def net_per_day_minor(self) -> int:
        return self.net_minor // max(1, self.days_active)


@dataclass(frozen=True, slots=True)
class PeriodicReport:
    start: str
    end: str
    currency: str
    points: tuple[tuple[str, str], ...]
    initiatives: tuple[InitiativeFigures, ...]

    def render(self) -> str:
        lines = [f"# Periodisk rapport {self.start} – {self.end} ({self.currency})", ""]
        if self.currency == "SIM":
            from ..simulation.readiness import MARKET_NOTE

            lines += [f"_{MARKET_NOTE} Siffrorna visar vad som händer om antagandena stämmer._", ""]
        lines += [
            f"{i}. **{name}:** {value}"
            for i, (name, value) in enumerate(self.points, 1)
        ]
        if self.initiatives:
            lines += [
                "",
                "| Initiativ | Intäkt | Kostnad | Netto | Marginal | Avkastning | Netto/dag | Sämsta dag |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for f in self.initiatives:
                lines.append(
                    f"| {f.initiative} | {f.revenue_minor} | {f.costs_minor} | {f.net_minor} | "
                    f"{_pct(f.margin_percent)} | {_pct(f.return_percent)} | {f.net_per_day_minor} | "
                    f"{f.worst_day_minor} |"
                )
        return "\n".join(lines) + "\n"


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f} %"


def periodic_report(system, start: str, end: str) -> PeriodicReport:
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError(f"perioden börjar efter att den slutar: {start} – {end}")
    currency = system.currency
    entries = system.ledger.entries(currency)
    before = tuple(e for e in entries if e.recorded_at[:10] < start)
    upto_end = tuple(e for e in entries if e.recorded_at[:10] <= end)
    period = tuple(e for e in upto_end if e.recorded_at[:10] >= start)
    limits = system.budget._limits
    opening = capital_position(before, limits).liquid_minor
    closing = capital_position(upto_end, limits).liquid_minor
    result = compute_result(period, currency)
    settled = [e for e in period if e.status is Status.SETTLED]
    cash_in = sum(e.amount_minor for e in settled if e.entry_type in _IN)
    cash_out = sum(e.amount_minor for e in settled if e.entry_type in _OUT)
    figures = _initiatives(period)
    findings = monitor(system, start)

    def amount(minor: int) -> str:
        return f"{minor} {currency}"

    departments = sorted({e.department for e in period})
    by_department = (
        "; ".join(
            f"{d} {compute_result(period, currency, department=d).net_minor}"
            for d in departments
        )
        or "SAKNAS: inga poster under perioden"
    )
    costs = result.costs_minor + result.fees_minor
    efficiency = (
        f"{result.revenue_minor / costs:.2f} kr intäkt per kr kostnad"
        if costs
        else "SAKNAS: inga kostnader under perioden"
    )
    points = (
        (
            POINTS[0],
            f"likvida medel {amount(opening)} → {amount(closing)} ({closing - opening:+d})",
        ),
        (
            POINTS[1],
            amount(result.net_minor) + (" (PRELIMINÄRT)" if result.preliminary else "")
            if period
            else "SAKNAS: inga poster under perioden",
        ),
        (
            POINTS[2],
            f"in {amount(cash_in)}, ut {amount(cash_out)}, netto {amount(cash_in - cash_out)}",
        ),
        (POINTS[3], by_department),
        (
            POINTS[4],
            "; ".join(f"{f.initiative} {f.net_minor}" for f in figures)
            or "SAKNAS: inga initiativ under perioden",
        ),
        (POINTS[5], _forecasts(system, start, end)),
        (POINTS[6], efficiency),
        (POINTS[7], _exposure(system, upto_end, limits)),
        (POINTS[8], _lessons(system, start, end)),
        (POINTS[9], _recommendations(figures, findings)),
    )
    return PeriodicReport(start, end, currency, points, figures)


def _initiatives(period) -> tuple[InitiativeFigures, ...]:
    daily: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    revenue: dict[str, int] = defaultdict(int)
    costs: dict[str, int] = defaultdict(int)
    for e in period:
        if e.status is not Status.SETTLED or not e.initiative:
            continue
        day = e.recorded_at[:10]
        if e.entry_type is EntryType.REVENUE:
            revenue[e.initiative] += e.amount_minor
            daily[e.initiative][day] += e.amount_minor
        elif e.entry_type in (EntryType.COST, EntryType.FEE, EntryType.REFUND):
            costs[e.initiative] += e.amount_minor
            daily[e.initiative][day] -= e.amount_minor
    return tuple(
        InitiativeFigures(
            name,
            revenue[name],
            costs[name],
            revenue[name] - costs[name],
            len(daily[name]),
            min(0, min(daily[name].values(), default=0)),
        )
        for name in sorted(daily)
    )


def _forecasts(system, start: str, end: str) -> str:
    compared = within = 0
    for f in system.forecasts.all():
        if not start <= f.due[:10] <= end or f.outcome is None:
            continue
        compared += 1
        actual = getattr(f.outcome, "actual", None)
        if (
            f.low is not None
            and f.high is not None
            and actual is not None
            and f.low <= actual <= f.high
        ):
            within += 1
    if not compared:
        return "SAKNAS: inga prognoser med utfall under perioden"
    return f"{within} av {compared} prognoser inom sitt intervall"


def _exposure(system, upto_end, limits) -> str:
    pos = capital_position(upto_end, limits)
    trips = len(system.stoploss.active())
    return f"åtaganden {pos.committed_minor} {pos.currency}, aktiva stop-loss {trips}"


def _lessons(system, start: str, end: str) -> str:
    found = [
        f"#{x.lesson_id} {x.statement} ({x.status})"
        for x in system.lessons.all()
        if start <= x.at[:10] <= end
    ]
    return "; ".join(found) or "inga nya lärdomar under perioden"


def _recommendations(figures, findings) -> str:
    out = [
        f"pröva att stoppa {f.initiative}: förlust {f.net_minor} under {f.days_active} dagar"
        for f in figures
        if f.net_minor < 0
    ]
    out += [f"undersök {x.kind} hos {x.subject}: {x.detail}" for x in findings]
    return "; ".join(out) or "inga förändringar föreslås"
