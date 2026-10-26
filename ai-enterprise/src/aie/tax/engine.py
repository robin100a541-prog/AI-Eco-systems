"""Tax Engine (Fas 4f, ER-18–21, D-010, D-032–D-034).

Systemet räknar och reserverar skatt, men avgör inte vilket spår som gäller. Det gör Skatteverket
utifrån verksamheten (Q-05). Satserna i `config/tax.toml` är simulerade och försiktiga.

**ER-18 Skattespår.** Varje intäkt (och återbetalning) märks med ett spår enligt D-010 och en fördelning
mellan grundarna: `assign()`. Spår C (enkelt bolag) fördelas enligt `partnership_shares`. Spår A, B och
D ägs av en grundare. En rättelse i ledgern ärver spåret från posten den rättar. Ett nytt spår för samma
post är en ny rad med motivering som pekar på den gamla (migration 21). Märker gör grundarna och roller
med verktyget `tax.assign` (CFO).

**ER-19 Reserverad skatt.** `reserved_minor()` = per spår och kalenderår: satsen × årets realiserade
bruttointäkt (intäkter − återbetalningar, bara `settled`), avrundat uppåt. En intäkt utan spår reserveras
med `untracked_rate`, som är högst. Reserven är ett åtagande: `BudgetEngine(tax=...)` drar den från det
disponibla kapitalet, så att pengarna aldrig kan investeras (`capital_position(tax_reserved_minor=)`).

**ER-20 Momsgränsen.** Årets försäljning är intäkter (`settled` och `pending`) − återbetalningar.
Vid 80 % loggas en varning, och vid gränsen blockeras ny försäljning (verktyg som börjar med `sales.`,
`publish.` eller `payment.`) tills **båda** grundarna har röstat med `vat_vote()`. Det är till exempel
efter momsregistrering. Ledgern tar fortfarande emot fakta (D-024).

**ER-21 Underlag.** Inget i ledgern eller i skattetabellerna kan raderas (triggers), så underlaget
finns kvar i minst 7 år. `export()` skriver ett deklarationsunderlag per grundare och år som JSON och
loggar filens SHA-256. Spår C får sin andel av årets kostnader och avgifter, som underlag för NE-bilagan.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..audit import AuditLog
from ..ledger import Entry, EntryType, Ledger, Status
from ..memory import Database
from .config import TRACKS, TaxConfig

ASSIGN_TOOL = "tax.assign"
ARCHIVE_YEARS = 7
SALES_PREFIXES = ("sales.", "publish.", "payment.")
_TAXABLE = frozenset({EntryType.REVENUE, EntryType.REFUND})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ceil_bp(amount: int, rate_bp: int) -> int:
    return -(-amount * rate_bp // 10_000)


class TaxError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Assignment:
    assignment_id: int
    entry_id: int
    track: str
    owners: dict[str, int]  # grundare → baspunkter, summa 10 000
    actor: str
    note: str
    corrects: int | None
    at: str


@dataclass(frozen=True, slots=True)
class TrackYear:
    track: str | None  # None = intäkter utan spår
    year: int
    gross_minor: int
    rate_bp: int
    reserved_minor: int
    entry_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TaxPosition:
    currency: str
    reserved_minor: int
    rows: tuple[TrackYear, ...]
    untracked: tuple[int, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VatStatus:
    year: int
    sales_minor: int
    threshold_minor: int
    level: str  # ok | warning | limit
    decided: bool  # båda grundarna har beslutat om gränsen
    votes: tuple[str, ...]

    @property
    def blocks_sales(self) -> bool:
        return self.level == "limit" and not self.decided


class TaxEngine:
    def __init__(
        self,
        db: Database,
        ledger: Ledger,
        config: TaxConfig,
        audit: AuditLog,
        founders: frozenset[str],
        engine=None,
        clock: Callable[[], str] = _now,
    ) -> None:
        """`engine`: en `AuthorizationEngine`, så att roller med `tax.assign` kan märka intäkter."""
        self._db = db
        self._ledger = ledger
        self._config = config
        self._audit = audit
        self._founders = frozenset(founders)
        self._engine = engine
        self._clock = clock

    # --- ER-18 skattespår ------------------------------------------------------------------

    def assign(self, actor: str, entry_id: int, track: str, owner: str | None = None, note: str = "") -> Assignment:
        self._require_assigner(actor)
        entry = self._ledger.get(entry_id)
        if entry is None:
            raise TaxError(f"ledgerposten {entry_id} finns inte")
        if entry.entry_type not in _TAXABLE:
            raise TaxError("bara intäkter och återbetalningar får ett skattespår (ER-18)")
        if entry.corrects is not None:
            raise TaxError("en rättelse ärver spåret från posten den rättar; märk originalet")
        if track not in TRACKS:
            raise TaxError(f"okänt spår {track!r} (D-010: {', '.join(TRACKS)})")
        if track == "partnership":
            if owner is not None:
                raise TaxError("spår C fördelas enligt partnership_shares i tax.toml, inte på en ägare")
            owners = dict(self._config.partnership_shares_bp)
        else:
            if owner not in self._founders:
                raise TaxError(f"spår {TRACKS[track]} ägs av en grundare; ange owner ({', '.join(sorted(self._founders))})")
            owners = {owner: 10_000}
        previous = self.assignment(entry_id)
        if previous is not None and not note.strip():
            raise TaxError(f"post {entry_id} har redan spåret {previous.track}; ett byte kräver en motivering")
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO tax_assignments (entry_id, track, owners, actor, note, corrects, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entry_id, track, json.dumps(owners, sort_keys=True), actor, note,
                 previous.assignment_id if previous else None, self._clock()),
            )
        self._audit.append(actor, "tax.reassigned" if previous else "tax.assigned",
                           {"entry_id": entry_id, "track": track, "owners": owners, "note": note})
        return self.assignment(entry_id)

    def assignment(self, entry_id: int) -> Assignment | None:
        """Gällande spår för en post. En rättelse i ledgern ärver från posten den rättar."""
        seen: set[int] = set()
        current = entry_id
        while current is not None and current not in seen:
            seen.add(current)
            row = self._db.connection.execute(
                "SELECT id, entry_id, track, owners, actor, note, corrects, at FROM tax_assignments "
                "WHERE entry_id = ? ORDER BY id DESC LIMIT 1", (current,)).fetchone()
            if row is not None:
                aid, eid, track, owners, actor, note, corrects, at = row
                return Assignment(aid, eid, track, json.loads(owners), actor, note, corrects, at)
            entry = self._ledger.get(current)
            current = entry.corrects if entry is not None else None
        return None

    def history(self, entry_id: int) -> tuple[Assignment, ...]:
        return tuple(
            Assignment(aid, eid, track, json.loads(owners), actor, note, corrects, at)
            for aid, eid, track, owners, actor, note, corrects, at in self._db.connection.execute(
                "SELECT id, entry_id, track, owners, actor, note, corrects, at FROM tax_assignments "
                "WHERE entry_id = ? ORDER BY id", (entry_id,))
        )

    # --- ER-19 reserverad skatt ------------------------------------------------------------

    def position(self, currency: str | None = None) -> TaxPosition:
        currency = currency or self._config.currency
        groups: dict[tuple[str | None, int], list[Entry]] = {}
        for e in self._taxable(currency, statuses=(Status.SETTLED,)):
            a = self.assignment(e.entry_id)
            groups.setdefault((a.track if a else None, int(e.recorded_at[:4])), []).append(e)
        rows = []
        for (track, year), entries in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0] or "~")):
            gross = sum(self._signed(e) for e in entries)
            rate = self._config.rates_bp[track] if track else self._config.untracked_rate_bp
            rows.append(TrackYear(track, year, gross, rate, _ceil_bp(max(0, gross), rate),
                                  tuple(e.entry_id for e in entries)))
        untracked = tuple(i for r in rows if r.track is None for i in r.entry_ids)
        notes = ["satserna är simulerade och försiktiga; spåret bekräftas med Skatteverket före Fas 7 (Q-05)"]
        if untracked:
            notes.append(f"intäkter utan spår reserveras med högsta satsen: {list(untracked)} (ER-18)")
        return TaxPosition(currency, sum(r.reserved_minor for r in rows), tuple(rows), untracked, tuple(notes))

    def reserved_minor(self, currency: str | None = None) -> int:
        return self.position(currency).reserved_minor

    # --- ER-20 momsgränsen -----------------------------------------------------------------

    def vat_status(self, year: int | None = None) -> VatStatus:
        year = year or int(self._clock()[:4])
        sales = sum(self._signed(e) for e in self._taxable(self._config.currency, (Status.SETTLED, Status.PENDING))
                    if int(e.recorded_at[:4]) == year and not (e.entry_type is EntryType.REFUND
                                                             and e.status is Status.PENDING))
        threshold = self._config.vat_threshold_minor
        if sales >= threshold:
            level = "limit"
        elif sales * 100 >= threshold * self._config.vat_warning_percent:
            level = "warning"
        else:
            level = "ok"
        votes = tuple(dict.fromkeys(self._events("vat_vote", year)))
        decided = bool(self._events("vat_decided", year))
        return VatStatus(year, sales, threshold, level, decided, votes)

    def check_vat(self, year: int | None = None) -> VatStatus:
        """Loggar varningen och gränsen en gång per år. Anropas av spärren; säkert att anropa ofta."""
        status = self.vat_status(year)
        for level, event in (("warning", "vat_warning"), ("limit", "vat_limit")):
            reached = status.level == "limit" or status.level == level
            if reached and not self._events(event, status.year):
                details = {"sales_minor": status.sales_minor, "threshold_minor": status.threshold_minor,
                           "notify": ["founders", "role:cfo"]}
                self._event(event, status.year, "system:tax", details)
                self._audit.append("system:tax", f"tax.{event}", {"year": status.year, **details})
        return status

    def vat_vote(self, founder: str, year: int, reason: str) -> VatStatus:
        """En grundares röst för att fortsätta sälja över momsgränsen. Båda krävs (D-033)."""
        if founder not in self._founders:
            raise TaxError("bara grundarna beslutar om momsgränsen (ER-20)")
        if not reason.strip():
            raise TaxError("ange beslutet, till exempel att verksamheten är momsregistrerad")
        status = self.vat_status(year)
        if status.level != "limit":
            raise TaxError(f"momsgränsen är inte nådd för {year}")
        if status.decided:
            raise TaxError(f"momsgränsen för {year} är redan beslutad")
        if founder in status.votes:
            raise TaxError(f"{founder} har redan röstat; den andra grundaren måste också rösta")
        self._event("vat_vote", year, founder, {"reason": reason})
        self._audit.append(founder, "tax.vat_vote", {"year": year, "reason": reason})
        votes = (*status.votes, founder)
        if set(votes) >= self._founders:
            self._event("vat_decided", year, founder, {"votes": list(votes)})
            self._audit.append(founder, "tax.vat_decided", {"year": year, "votes": list(votes)})
        return self.vat_status(year)

    def tool_block_reason(self, agent, tool: str) -> str | None:
        """För AuthorizationEngine: ny försäljning blockeras vid momsgränsen (ER-20)."""
        if not tool.startswith(SALES_PREFIXES):
            return None
        status = self.check_vat()
        if not status.blocks_sales:
            return None
        return (f"momsgränsen är nådd för {status.year}: {status.sales_minor} ≥ {status.threshold_minor} "
                f"{self._config.currency}; ny försäljning blockeras tills båda grundarna har beslutat (ER-20)")

    # --- ER-21 underlag --------------------------------------------------------------------

    def export(self, founder: str, year: int, out_dir: Path | str) -> Path:
        """Deklarationsunderlag för en grundare och ett år. Filen loggas med SHA-256."""
        if founder not in self._founders:
            raise TaxError("underlag exporteras per grundare")
        currency = self._config.currency
        tracks: dict[str, dict] = {}
        for e in self._taxable(currency, (Status.SETTLED,)):
            if int(e.recorded_at[:4]) != year:
                continue
            a = self.assignment(e.entry_id)
            key = a.track if a else "untracked"
            share = a.owners.get(founder, 0) if a else 0
            if a is not None and share == 0:
                continue
            bucket = tracks.setdefault(key, {"label": TRACKS.get(key, "utan spår"), "gross_minor": 0, "entries": []})
            amount = self._signed(e) * share // 10_000 if a else self._signed(e)
            bucket["gross_minor"] += amount
            bucket["entries"].append({"entry_id": e.entry_id, "type": e.entry_type.value, "amount_minor": e.amount_minor,
                                      "share_bp": share, "your_amount_minor": amount, "initiative": e.initiative,
                                      "recorded_at": e.recorded_at, "evidence": list(e.evidence),
                                      "external_id": e.external_id})
        share_c = self._config.partnership_shares_bp.get(founder, 0)
        costs = [e for e in self._ledger.entries(currency) if e.status is Status.SETTLED
                 and e.entry_type in (EntryType.COST, EntryType.FEE) and int(e.recorded_at[:4]) == year]
        if "partnership" in tracks:
            tracks["partnership"]["costs_share_minor"] = sum(e.amount_minor for e in costs) * share_c // 10_000
            tracks["partnership"]["cost_entry_ids"] = [e.entry_id for e in costs]
        payload = {
            "founder": founder, "year": year, "currency": currency, "archive_until": year + ARCHIVE_YEARS,
            "tracks": tracks,
            "notes": ["underlag, inte en deklaration; satser och spår bekräftas med Skatteverket (Q-05)",
                      "intäkter utan spår ska märkas innan deklarationen" if "untracked" in tracks else "alla intäkter har spår"],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"deklarationsunderlag-{year}-{founder}.json"
        path.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self._event("export", year, founder, {"file": path.name, "sha256": digest})
        self._audit.append(founder, "tax.exported", {"year": year, "file": path.name, "sha256": digest})
        return path

    def exports(self, year: int | None = None) -> tuple[dict, ...]:
        rows = self._db.connection.execute(
            "SELECT year, actor, details, at FROM tax_events WHERE event = 'export' ORDER BY id").fetchall()
        return tuple({"year": y, "founder": a, **json.loads(d), "at": at} for y, a, d, at in rows
                     if year is None or y == year)

    # --- Internt ---------------------------------------------------------------------------

    def _taxable(self, currency: str, statuses) -> list[Entry]:
        return [e for e in self._ledger.entries(currency) if e.entry_type in _TAXABLE and e.status in statuses]

    @staticmethod
    def _signed(e: Entry) -> int:
        return -e.amount_minor if e.entry_type is EntryType.REFUND else e.amount_minor

    def _require_assigner(self, actor: str) -> None:
        if actor in self._founders:
            return
        if self._engine is None or not self._engine.check(actor, ASSIGN_TOOL).allowed:
            raise TaxError("skattespår märks av grundarna eller roller med tax.assign (CFO)")

    def _events(self, event: str, year: int) -> list[str]:
        return [r[0] for r in self._db.connection.execute(
            "SELECT actor FROM tax_events WHERE event = ? AND year = ? ORDER BY id", (event, year))]

    def _event(self, event: str, year: int, actor: str, details: dict) -> None:
        with self._db.transaction() as tx:
            tx.execute("INSERT INTO tax_events (event, year, actor, details, at) VALUES (?, ?, ?, ?, ?)",
                       (event, year, actor, json.dumps(details, ensure_ascii=False), self._clock()))
