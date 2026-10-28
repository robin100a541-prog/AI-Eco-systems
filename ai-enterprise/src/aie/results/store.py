"""Utfall från verkligheten: import, sammanställning och jämförelse med prognosen (PR 10, D-062).

En grundare importerar en CSV-fil med en rad per dag och initiativ:

```csv
day,initiative,visitors,orders,revenue_minor,refunds_minor,fees_minor,costs_minor,currency,source,note
2027-02-01,mallar,35,1,4900,0,520,0,SEK,https://exempel.se/rapport/2027-02-01,första dagen
```

- Belopp är heltal i minsta enhet (öre eller cent, D-006). `currency` är SEK eller USD.
- `source` krävs på varje rad: en URL, en fil eller ett kvitto som visar siffrorna. Ordet "antagande" är inte en källa.
- Hela filen avvisas om en rad är fel. Ingenting sparas då.
- Samma rad två gånger sparas en gång. En rättelse är en ny rad med en egen källa.

Allt som importeras märks **verifierat i verkligheten**. När ett initiativ har minst `MIN_DAYS` dagar med
utfall ersätter de uppmätta värdena antagandena i bedömningen före start (D-058). Det gäller besökare,
konvertering, återbetalningar och avgifter när plattformens avgift är okänd. Rapporten visar prognos mot utfall.
"""
from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from ..audit import AuditLog
from ..memory import Database

COLUMNS = ("day", "initiative", "visitors", "orders", "revenue_minor", "refunds_minor", "fees_minor", "costs_minor",
           "currency", "source", "note")
_INTS = ("visitors", "orders", "revenue_minor", "refunds_minor", "fees_minor", "costs_minor")
CURRENCIES = ("SEK", "USD")
MIN_DAYS = 7  # färre dagar än så är för lite för att ersätta ett antagande
VERIFIED = "verifierat i verkligheten"


class ResultError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class Observed:
    """Summan av utfallen för ett initiativ, i en valuta."""
    initiative: str
    currency: str
    days: int
    first_day: str
    last_day: str
    visitors: int
    orders: int
    revenue_minor: int
    refunds_minor: int
    fees_minor: int
    costs_minor: int
    sources: tuple[str, ...]

    @property
    def net_minor(self) -> int:
        return self.revenue_minor - self.refunds_minor - self.fees_minor - self.costs_minor

    @property
    def visitors_per_day(self) -> int:
        return round(self.visitors / self.days) if self.days else 0

    @property
    def conversion_bp(self) -> int | None:
        return round(self.orders * 10_000 / self.visitors) if self.visitors else None

    @property
    def refund_bp(self) -> int | None:
        return round(self.refunds_minor * 10_000 / self.revenue_minor) if self.revenue_minor else None

    @property
    def fee_per_order_minor(self) -> int | None:
        return round(self.fees_minor / self.orders) if self.orders else None


def parse_csv(text: str, known_initiatives, today: str) -> list[dict]:
    """Rader ur en CSV-fil. Kastar `ResultError` med alla fel. Då importeras ingenting."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None or tuple(h.strip() for h in reader.fieldnames) != COLUMNS:
        raise ResultError(f"kolumnerna ska vara exakt: {','.join(COLUMNS)}")
    rows, errors = [], []
    for n, raw in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k is not None}
        problems = []
        try:
            if date.fromisoformat(row["day"]).isoformat() > today:
                problems.append("dagen ligger i framtiden")
        except ValueError:
            problems.append("day ska vara ÅÅÅÅ-MM-DD")
        if row["initiative"] not in known_initiatives:
            problems.append(f"initiativet {row['initiative']!r} finns inte i registret")
        for key in _INTS:
            value = row[key]
            if not value.isdigit():
                problems.append(f"{key} ska vara ett heltal ≥ 0 i minsta enhet")
            else:
                row[key] = int(value)
        if row["currency"] not in CURRENCIES:
            problems.append(f"currency ska vara {' eller '.join(CURRENCIES)}")
        if len(row["source"]) < 5 or "antagande" in row["source"].lower():
            problems.append("source krävs: en URL, en fil eller ett kvitto som visar siffrorna")
        if not problems and row["orders"] > row["visitors"] > 0:
            problems.append("fler order än besökare")
        if problems:
            errors.append(f"rad {n}: " + "; ".join(problems))
        else:
            rows.append(row)
    if errors:
        raise ResultError("filen importeras inte:\n" + "\n".join(f"  - {e}" for e in errors))
    if not rows:
        raise ResultError("filen har inga rader")
    return rows


def _row_hash(row: dict) -> str:
    return hashlib.sha256("\x1f".join(str(row[k]) for k in COLUMNS).encode("utf-8")).hexdigest()


class ResultStore:
    def __init__(self, db: Database, audit: AuditLog, founders: frozenset[str], register=None,
                 clock: Callable[[], str] = _now) -> None:
        self._db = db
        self._audit = audit
        self._founders = frozenset(founders)
        self._register = register
        self._clock = clock

    def import_csv(self, founder: str, text: str) -> tuple[int, int]:
        """Importerar filen. Returnerar (nya rader, rader som redan fanns)."""
        if founder not in self._founders:
            raise ResultError("bara en grundare importerar utfall (D-062)")
        known = {e.key for e in self._register.all("initiative")} if self._register is not None else set()
        rows = parse_csv(text, known, self._clock()[:10])
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        new = 0
        with self._db.transaction() as tx:
            for row in rows:
                cursor = tx.execute(
                    "INSERT OR IGNORE INTO real_results (day, initiative, visitors, orders, revenue_minor, "
                    "refunds_minor, fees_minor, costs_minor, currency, source, note, row_hash, file_sha256, "
                    "imported_by, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*(row[k] for k in COLUMNS), _row_hash(row), file_hash, founder, self._clock()))
                new += cursor.rowcount
        self._audit.append(founder, "results.imported", {"rows": len(rows), "new": new, "file_sha256": file_hash})
        return new, len(rows) - new

    def observed(self, initiative: str) -> tuple[Observed, ...]:
        """Summan per valuta. Bara dagar med utfall räknas."""
        out = []
        for currency, in self._db.connection.execute(
                "SELECT DISTINCT currency FROM real_results WHERE initiative = ? ORDER BY currency", (initiative,)):
            row = self._db.connection.execute(
                "SELECT COUNT(DISTINCT day), MIN(day), MAX(day), SUM(visitors), SUM(orders), SUM(revenue_minor), "
                "SUM(refunds_minor), SUM(fees_minor), SUM(costs_minor) FROM real_results "
                "WHERE initiative = ? AND currency = ?", (initiative, currency)).fetchone()
            sources = tuple(r[0] for r in self._db.connection.execute(
                "SELECT DISTINCT source FROM real_results WHERE initiative = ? AND currency = ? ORDER BY source",
                (initiative, currency)))
            out.append(Observed(initiative, currency, *row, sources))
        return tuple(out)

    def initiatives(self) -> tuple[str, ...]:
        return tuple(r[0] for r in self._db.connection.execute(
            "SELECT DISTINCT initiative FROM real_results ORDER BY initiative"))

    def report(self, initiative: str) -> dict:
        """Prognos mot utfall. Prognosen kommer från den senaste godkända bedömningen och registret (simulerat)."""
        entry = self._register.get("initiative", initiative) if self._register is not None else None
        assessment = None
        if self._register is not None:
            approved = [a for a in self._register.assessments.for_initiative(initiative) if a.decision == "approved"]
            assessment = approved[-1] if approved else None
        forecast = {}
        if assessment is not None:
            scenarios = assessment.result.get("scenarios", {})
            forecast = {name: s.get("daily_net_minor") for name, s in scenarios.items()}
        demand = entry.data.get("demand", {}) if entry else {}
        rows = []
        for o in self.observed(initiative):
            rows.append({
                "currency": o.currency, "days": o.days, "period": f"{o.first_day}–{o.last_day}",
                "label": VERIFIED, "sources": list(o.sources),
                "outcome": {"net_per_day_minor": round(o.net_minor / o.days), "visitors_per_day": o.visitors_per_day,
                            "conversion_bp": o.conversion_bp, "refund_bp": o.refund_bp,
                            "fee_per_order_minor": o.fee_per_order_minor},
                "forecast": {"label": "simulerat", "assessment_id": assessment.assessment_id if assessment else None,
                             "net_per_day_minor": forecast,
                             "visitors_per_day": demand.get("visitors_per_day"),
                             "conversion_bp": demand.get("conversion_bp"), "refund_bp": demand.get("refund_bp")},
                "enough_days": o.days >= MIN_DAYS,
            })
        return {"initiative": initiative, "results": rows,
                "note": "Prognosen gäller SIM, utfallet sin egen valuta. Belopp i USD räknas om i bedömningen."}
