"""Daglig rapport (FR-21, konstitutionen §57, D-045).

`daily_report(system, day)` sammanställer de elva punkterna i §57 direkt ur ledgern och spärrarna, så
att rapporten alltid motsvarar transaktionsdata (§54). Saknas data för en punkt står det uttryckligen
`SAKNAS: <skäl>` i stället för en siffra, aldrig en nolla som ser ut som ett riktigt värde.

Perioden är ett dygn (`day`, `ÅÅÅÅ-MM-DD`) räknat på postens `recorded_at`, som i en simulering är
affärstiden. Kapital, reserv, åtaganden och budget är ställningen vid rapporttillfället.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..budget.capital import capital_position
from ..ledger import EntryType, Status, compute_result

POINTS = (
    "Disponibelt kapital",
    "Skyddad reserv",
    "Intäkter under perioden",
    "Kostnader under perioden",
    "Realiserad nettovinst eller nettoförlust",
    "Öppna ekonomiska åtaganden",
    "Budgetutnyttjande",
    "Aktiva affärsinitiativ",
    "Viktiga risker",
    "Kritiska fel",
    "Beslut som väntar på godkännande",
)
_COSTS = (EntryType.COST, EntryType.FEE)


def missing(reason: str) -> str:
    return f"SAKNAS: {reason}"


@dataclass(frozen=True, slots=True)
class DailyReport:
    day: str
    currency: str
    points: tuple[tuple[str, str], ...]  # (punkt i §57, värde eller SAKNAS: skäl)

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(name for name, value in self.points if value.startswith("SAKNAS"))

    def render(self) -> str:
        lines = [f"# Daglig rapport {self.day} ({self.currency})", ""]
        if self.currency == "SIM":
            from ..simulation.readiness import MARKET_NOTE

            lines += [f"_{MARKET_NOTE} Siffrorna visar vad som händer om antagandena stämmer._", ""]
        lines += [
            f"{i}. **{name}:** {value}"
            for i, (name, value) in enumerate(self.points, 1)
        ]
        if self.missing:
            lines += [
                "",
                f"Data saknas för {len(self.missing)} av {len(POINTS)} punkter.",
            ]
        return "\n".join(lines) + "\n"


def daily_report(system, day: str) -> DailyReport:
    currency = system.currency
    entries = system.ledger.entries(currency)
    today = tuple(e for e in entries if e.recorded_at[:10] == day)
    # En dag utan poster efter att ledgern startat är en dag utan affärer (0), inte saknade data.
    has_data = any(e.recorded_at[:10] <= day for e in entries)
    quiet = "" if today else " (inga poster under dagen)"
    limits = system.budget._limits  # samma gränser som budgetmotorn använder
    tax = system.tax.reserved_minor(currency) if system.tax is not None else None
    pos = capital_position(entries, limits, tax)

    def amount(minor: int) -> str:
        return f"{minor} {currency}"

    settled = [e for e in today if e.status is Status.SETTLED]
    revenue = sum(e.amount_minor for e in settled if e.entry_type is EntryType.REVENUE)
    refunds = sum(e.amount_minor for e in settled if e.entry_type is EntryType.REFUND)
    costs = sum(e.amount_minor for e in settled if e.entry_type in _COSTS)
    result = compute_result(today, currency)
    net = amount(result.net_minor) + (
        f" (PRELIMINÄRT: {'; '.join(result.reasons)})" if result.preliminary else ""
    )

    points = [
        (
            POINTS[0],
            amount(pos.disposable_minor)
            if pos.reserve_minor is not None
            else missing(
                "MINIMUM_RESERVE saknas; inget kapital får disponeras (ER-02)"
            ),
        ),
        (
            POINTS[1],
            amount(pos.reserve_minor)
            if pos.reserve_minor is not None
            else missing("MINIMUM_RESERVE saknas i risk_limits.toml"),
        ),
        (
            POINTS[2],
            amount(revenue - refunds)
            + (f" (brutto {revenue}, återbetalt {refunds})" if refunds else "")
            if has_data
            else missing("ledgern har inga poster till och med dagen"),
        ),
        (
            POINTS[3],
            amount(costs) + quiet if has_data else missing("ledgern har inga poster till och med dagen"),
        ),
        (POINTS[4], net if has_data else missing("ledgern har inga poster till och med dagen")),
        (POINTS[5], amount(pos.committed_minor)),
        (POINTS[6], _budget_usage(system)),
        (POINTS[7], _initiatives(system, entries)),
        (POINTS[8], _risks(system)),
        (POINTS[9], _critical(system)),
        (POINTS[10], _pending(system)),
    ]
    return DailyReport(day, currency, tuple(points))


def _budget_usage(system) -> str:
    if not system.budgets:
        return missing("inga departementsbudgetar i budgets.toml")
    parts = []
    for department in sorted(system.budgets):
        spent, left = system.budget.usage(department)
        parts.append(
            f"{department} {spent} använt, {left if left is not None else '?'} kvar"
        )
    return "; ".join(parts)


def _initiatives(system, entries) -> str:
    stopped = {
        t.scope_value for t in system.stoploss.active() if t.scope_kind == "initiative"
    }
    business = (EntryType.REVENUE, EntryType.COST, EntryType.FEE, EntryType.REFUND)  # inte kapital eller skatt
    active = sorted({e.initiative for e in entries if e.initiative and e.entry_type in business} - stopped)
    if not active and not stopped:
        return "inga"
    text = ", ".join(active) or "inga"
    return text + (
        f" (stoppade av stop-loss: {', '.join(sorted(stopped))})" if stopped else ""
    )


def _risks(system) -> str:
    risks = []
    kill = system.kill.state()
    if kill.engaged:
        risks.append(f"NÖDSTOPP aktivt: {kill.reason}")
    mode = system.protected.state()
    if mode.protected:
        risks.append("skyddat driftläge: " + "; ".join(mode.reasons))
    for trip in system.stoploss.active():
        risks.append(
            f"stop-loss {trip.limit_name} för {trip.scope_kind} {trip.scope_value}: "
            f"{trip.measured} av {trip.limit_value} {trip.currency}"
        )
    return "; ".join(risks) or "inga aktiva stopp eller gränsöverträdelser"


def _critical(system) -> str:
    errors = [
        f"incident #{i.incident_id}: {i.title}"
        for i in system.incidents.open_incidents()
    ]
    errors += [f"systemfel: {e}" for e in system.errors]
    return "; ".join(errors) or "inga öppna incidenter eller systemfel"


def _pending(system) -> str:
    items = []
    if system.spend_approvals is not None:
        items += [
            f"utgift #{a.approval_id} {a.department}/{a.initiative} {a.amount_minor} {a.currency}"
            for a in system.spend_approvals.pending()
        ]
    if system.db is not None:
        rows = system.db.connection.execute(
            "SELECT request_id, kind, reason FROM approval_requests WHERE status = 'pending' ORDER BY request_id"
        ).fetchall()
        items += [f"{kind} #{rid}: {reason}" for rid, kind, reason in rows]
    return "; ".join(items) or "inga"


def save_daily_reports(system, data_dir) -> list:
    """Skriver en rapport per affärsdag i ledgern till `<data_dir>/reports/daily-ÅÅÅÅ-MM-DD.md`."""
    from pathlib import Path

    out = Path(data_dir) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for day in sorted({e.recorded_at[:10] for e in system.ledger.entries(system.currency)}):
        path = out / f"daily-{day}.md"
        path.write_text(daily_report(system, day).render(), encoding="utf-8")
        paths.append(path)
    return paths
