"""Piloten med riktiga pengar (Fas 7b): förbered, godkänn, importera försäljning och stoppa.

Riktiga pengar blandas aldrig med SIM. Piloten har en egen databas i miljön `prod` med valutan SEK,
under `data-pilot/` (gitignorerad). Konfigurationen härleds vid varje körning ur repots `config/`:
samma gränser och samma behörigheter, bara miljö och valuta byts (`pilot_config`). SIM kan därför
aldrig registreras i piloten, och SEK aldrig i simuleringen (ER-15, ledgern kontrollerar det).

- `prepare`: visar listningen, priset, budgeten (taket är START_CAPITAL, 500 kr), stop-loss
  (MAX_SINGLE_EXPERIMENT_LOSS) och stoppkriterierna, och lägger "godkänn piloten" i grundarnas
  godkännandekö. Beslutet ligger över HUMAN_APPROVAL_THRESHOLD, så ingen agent kan fatta det.
- `approve`: en grundare godkänner förfrågan i kön (D-049: en grundare räcker).
- `import_sales`: en grundare klistrar in plattformens försäljnings-CSV. Varje försäljning blir intäkt och
  avgift i ledgern (SEK, med den kurs grundaren anger), en återbetalning blir en egen post, och samma
  försäljning två gånger bokförs en gång. Skatten reserveras av Tax Engine (utan valt spår med
  `untracked_rate`, eftersom Q-TAX-01 är öppen). Summorna stäms av mot plattformens totalsumma (ER-23);
  en skillnad blir en incident.
- `check_stops`: stop-loss och stoppkriterierna gäller riktiga data. När något slår till sätts
  skyddat läge, som stoppar nya utgifter, och rapporten rekommenderar att produkten avpubliceras.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from .settings import SETTINGS

CURRENCY = "SEK"
INITIATIVE_PREFIX = "pilot-"
NO_SALE_DAYS = 60  # ingen försäljning så här länge efter godkännandet = stoppa
REFUND_STOP_RATIO = (1, 3)  # minst en återbetalning per tre försäljningar (minst tre) = stoppa
_ALIASES = SETTINGS.csv  # kolumnnamnen ligger i config/pilot.toml (D-056)


class PilotError(ValueError):
    """Pilotåtgärden kunde inte göras; inget ändrades."""


def pilot_config(repo_config: Path, root: Path) -> Path:
    """Härleder pilotens konfiguration (prod, SEK) ur repots config/. Returnerar mappen."""
    out = Path(root) / "config"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(repo_config, out)
    system = (out / "system.toml").read_text(encoding="utf-8")
    system = re.sub(r'(?m)^environment = .*$', 'environment = "prod"', system)
    system = re.sub(r'(?m)^base_currency = .*$', f'base_currency = "{CURRENCY}"', system)
    system = re.sub(r'(?m)^data_dir = .*$', f'data_dir = "{(Path(root) / "data").as_posix()}"', system)
    system = re.sub(r'(?m)^log_dir = .*$', f'log_dir = "{(Path(root) / "logs").as_posix()}"', system)
    (out / "system.toml").write_text(system, encoding="utf-8")
    for name in ("risk_limits.toml", "tax.toml"):
        text = (out / name).read_text(encoding="utf-8")
        (out / name).write_text(re.sub(r'(?m)^currency = "SIM"', f'currency = "{CURRENCY}"', text), encoding="utf-8")
    return out


def load_idea(product_dir: Path) -> dict:
    path = Path(product_dir) / "idea.json"
    if not path.is_file():
        raise PilotError(f"{path} saknas; kör först `aie pilot ideas`")
    return json.loads(path.read_text(encoding="utf-8"))


def initiative_for(idea: dict) -> str:
    return INITIATIVE_PREFIX + idea["id"]


def prepare(gov, limits, founder: str, product_dir: Path) -> tuple[str, object]:
    """Text för grundaren och förfrågan i godkännandekön."""
    from ..governance import DecisionDraft, RiskClass
    from ..simulation.agents import ensure_org

    idea = load_idea(product_dir)
    listing = (Path(product_dir) / "listing.md").read_text(encoding="utf-8")
    cap = limits.start_capital.amount_minor
    stop = limits.max_single_experiment_loss.amount_minor
    ensure_org(gov.registry, founder)
    task = gov.board.create(founder, f"Fas 7: godkänn piloten {idea['id']}", "manuell listning")
    gov.board.assign(founder, task.task_id, "ceo-1", "piloten (Fas 7b)")
    draft = DecisionDraft(
        f"Starta piloten {initiative_for(idea)}: en grundare listar produkten för hand på plattformen",
        "Produkten valdes i beslutscykeln (7a/7c). Inga förskottskostnader; plattformen tar avgift först vid försäljning.",
        (f"{product_dir}/idea.json", f"{product_dir}/listing.md", "efterfrågan overifierad (D-063)"),
        cap, RiskClass.LOW,
        f"hypotes: {idea['expected_sales_90d']} försäljningar på 90 dagar, netto "
        f"{idea['expected_net_90d_cents'] / 100:.2f} USD",
        f"stop-loss {stop / 100:.2f} kr; {idea['stop_criteria']}; ingen försäljning på {NO_SALE_DAYS} dagar",
        "importera plattformens försäljning varje vecka med `aie results import --format <plattform>`")
    request = gov.queue.submit_decision("ceo-1", task.task_id, draft)
    text = "\n".join([
        listing.rstrip(), "",
        "## Pilotens ramar",
        f"- Budgettak: {cap / 100:.2f} kr (START_CAPITAL); inga förskottskostnader planeras",
        f"- Stop-loss: {stop / 100:.2f} kr förlust (MAX_SINGLE_EXPERIMENT_LOSS)",
        f"- Stoppkriterier: {idea['stop_criteria']}; ingen försäljning på {NO_SALE_DAYS} dagar; "
        f"återbetalningar {REFUND_STOP_RATIO[0]} av {REFUND_STOP_RATIO[1]} försäljningar",
        f"- Godkännande: förfrågan #{getattr(request, 'request_id', '?')} i godkännandekön. "
        f"Kör `python -m aie pilot approve {getattr(request, 'request_id', '<id>')} --as <grundare>`.",
    ])
    return text + "\n", request


def approve(gov, system, founder: str, request_id: int):
    """Godkänner förfrågan och bokför pilotkapitalet (START_CAPITAL) som grundarna har avsatt."""
    from ..ledger import Approval, EntryDraft, EntryType, Status

    founder = founder.lower()
    request = gov.queue.approve(founder, request_id, "piloten godkänd (Fas 7b)")
    if request.status.value == "approved":
        system.ledger.record(founder, EntryDraft(
            f"pilot-capital-{request_id}", "finance", request.amount_minor, CURRENCY, EntryType.CAPITAL_IN, "pilotkapital",
            Approval.APPROVED, (f"approval:{request_id}",), status=Status.SETTLED,
            note="pilotkapital som grundarna har avsatt (Fas 7b)"))
    return request


def approval(db, initiative: str) -> tuple[int, str] | None:
    """(beslutets nummer, tidpunkt) när en grundare godkände piloten i godkännandekön, eller None.

    Härleds bara ur kön (granskning N3): förfrågan ska vara av typen decision, godkänd, höra till uppgiften
    som `prepare` skapade och ha ett beslut som utfall. Ett agentbeslut med samma text räknas aldrig.
    """
    idea_id = initiative.removeprefix(INITIATIVE_PREFIX)
    row = db.connection.execute(
        "SELECT r.outcome_decision, r.decided_at FROM approval_requests r JOIN tasks t ON t.task_id = r.task_id "
        "WHERE r.kind = 'decision' AND r.status = 'approved' AND r.outcome_decision IS NOT NULL "
        "AND t.title = ? ORDER BY r.request_id DESC LIMIT 1",
        (f"Fas 7: godkänn piloten {idea_id}",)).fetchone()
    return (row[0], row[1]) if row else None


@dataclass
class ImportResult:
    sales: int = 0
    refunds: int = 0
    duplicates: int = 0
    gross_minor: int = 0
    fees_minor: int = 0
    refunds_minor: int = 0
    mismatch: str | None = None
    incident_id: int | None = None
    notes: list = field(default_factory=list)

    @property
    def net_minor(self) -> int:
        return self.gross_minor - self.fees_minor - self.refunds_minor


def _column(header: list[str], key: str) -> str:
    lowered = {h.strip().lower(): h for h in header}
    for alias in _ALIASES[key]:
        if alias in lowered:
            return lowered[alias]
    raise PilotError(f"kolumnen för {key} saknas (väntade en av: {', '.join(_ALIASES[key])})")


def _decimal(value, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise PilotError(f"ogiltigt {label}") from exc
    if not number.is_finite():
        raise PilotError(f"ogiltigt {label}")
    return number


def _usd_cents(text: str) -> int:
    value = _decimal(text.strip().replace("$", "").replace(",", "") or "0", "belopp")
    cents = value * 100
    if value < 0 or cents != cents.to_integral_value():
        raise PilotError("beloppet måste vara icke-negativt med högst två decimaler")
    return int(cents)


def parse_sales_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise PilotError("CSV-filen är tom")
    cols = {k: _column(reader.fieldnames, k) for k in ("id", "date", "price", "fee")}
    refunded = next((h for h in reader.fieldnames if h.strip().lower() in _ALIASES["refunded"]), None)
    refund_date = next((h for h in reader.fieldnames if h.strip().lower() in
                        ("refund date", "refund_date", "refunded at", "refunded_at")), None)
    rows, unique = [], {}
    for n, r in enumerate(reader, 2):
        sale_id = (r.get(cols["id"]) or "").strip()
        if not sale_id:
            raise PilotError(f"rad {n}: försäljnings-ID saknas")
        day = (r.get(cols["date"]) or "").strip()[:10]
        flag = (r.get(refunded) or "").strip().lower() if refunded else ""
        if flag not in ("true", "yes", "ja", "1", "false", "no", "nej", "0", ""):
            raise PilotError(f"rad {n}: okänd återbetalningsstatus")
        is_refund = flag in ("true", "yes", "ja", "1")
        refund_day = (r.get(refund_date) or "").strip()[:10] if refund_date else ""
        try:
            date.fromisoformat(day)
            if is_refund:
                if not refund_day:
                    raise PilotError(f"rad {n}: återbetalning kräver Refund Date; datum får inte gissas")
                date.fromisoformat(refund_day)
                if refund_day < day:
                    raise PilotError(f"rad {n}: återbetalningen är före försäljningen")
        except ValueError as exc:
            if isinstance(exc, PilotError):
                raise
            raise PilotError(f"rad {n}: ogiltigt händelsedatum") from exc
        row = {"id": sale_id, "day": day, "price": _usd_cents(r.get(cols["price"]) or ""),
               "fee": _usd_cents(r.get(cols["fee"]) or ""), "refunded": is_refund,
               "refund_day": refund_day if is_refund else None}
        if sale_id in unique and unique[sale_id] != row:
            raise PilotError(f"rad {n}: motstridiga rader för samma försäljnings-ID")
        unique[sale_id] = row
        rows.append(row)
    return rows


def import_sales(system, founder: str, initiative: str, text: str, usd_sek: float,
                 reported_net_usd: float | None) -> ImportResult:
    """Atomic event import; later refunds do not get skipped as duplicate sales."""
    from ..ledger import Approval, EntryDraft, EntryType, Status

    if system.currency == "SIM":
        raise PilotError("riktig försäljning bokförs aldrig i en SIM-databas (ER-15)")
    rate = _decimal(usd_sek, "växelkurs")
    if rate <= 0:
        raise PilotError("växelkursen måste vara större än 0")
    approved = approval(system.db, initiative)
    if approved is None:
        raise PilotError(f"piloten {initiative} är inte godkänd; kör `aie pilot prepare` och `aie pilot approve` först")
    rows = parse_sales_csv(text)
    reported = None if reported_net_usd is None else _decimal(reported_net_usd, "plattformsnetto") * 100
    if reported is not None and reported != reported.to_integral_value():
        raise PilotError("plattformsnetto måste ha högst två decimaler")
    file_sha = hashlib.sha256(text.encode()).hexdigest()
    result, seen = ImportResult(), set()
    convert = lambda cents, fx: int((Decimal(cents) * fx).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    # Nested ledger/audit operations use savepoints. Failures roll back the whole batch.
    with system.db.transaction():
        known = {e.external_id: e for e in system.ledger.entries(CURRENCY) if e.external_id}
        ledger_net = csv_net = expected_ledger_net = 0
        for row in rows:
            key = f"{SETTINGS.platform_key}:{row['id']}"
            if key in seen:
                result.duplicates += 1
                continue
            seen.add(key)
            evidence = (f"file:{SETTINGS.platform_key}-csv/{file_sha[:16]}", f"external:kurs-usd-sek/{rate}",
                        f"decision:{approved[0]}")
            posts = [("sale", EntryType.REVENUE, row["price"], row["day"]),
                     ("fee", EntryType.FEE, row["fee"], row["day"])]
            if row["refunded"]:
                posts.append(("refund", EntryType.REFUND, row["price"], row["refund_day"]))
            new_sale = new_refund = changed = False
            for suffix, kind, cents, day in posts:
                external_id = f"{key}:{suffix}"
                existing = known.get(external_id)
                fx = rate
                if existing is not None:
                    fx_text = next((v.split("external:kurs-usd-sek/", 1)[1] for v in existing.evidence
                                    if v.startswith("external:kurs-usd-sek/")), None)
                    if fx_text is None:
                        raise PilotError(f"{external_id}: kursunderlag saknas; granska den äldre posten")
                    fx = _decimal(fx_text, "tidigare växelkurs")
                amount = convert(cents, fx)
                if existing is not None:
                    if (existing.initiative != initiative or existing.entry_type is not kind
                            or existing.amount_minor != amount or existing.status is not Status.SETTLED
                            or existing.occurred_on is None or existing.economic_date != day):
                        raise PilotError(f"{external_id}: ändrat underlag eller äldre post utan händelsedatum; "
                                         "kräver spårbar rättelse")
                elif amount:
                    existing = system.ledger.record(founder, EntryDraft(
                        external_id, "research", amount, CURRENCY, kind, initiative, Approval.APPROVED, evidence,
                        external_id=external_id, status=Status.SETTLED,
                        note=f"{SETTINGS.platform} {day}", occurred_on=day))
                    known[external_id] = existing
                    changed = True
                    new_sale |= suffix == "sale"
                    new_refund |= suffix == "refund"
                    if suffix == "sale":
                        result.gross_minor += amount
                    elif suffix == "fee":
                        result.fees_minor += amount
                    else:
                        result.refunds_minor += amount
                sign = -1 if kind in (EntryType.FEE, EntryType.REFUND) else 1
                expected_ledger_net += sign * amount
                ledger_net += sign * (existing.amount_minor + sum(c.amount_minor for c in system.ledger.corrections(existing.entry_id))
                                      if existing else 0)
            if not row["refunded"] and f"{key}:refund" in known:
                raise PilotError(f"{key}: exporten saknar en redan bokförd återbetalning")
            result.sales += int(new_sale)
            result.refunds += int(new_refund)
            result.duplicates += int(not changed)
            csv_net += row["price"] - row["fee"] - (row["price"] if row["refunded"] else 0)
        if ledger_net != expected_ledger_net:
            raise PilotError("ledgerns netto stämmer inte med importens beständiga poster")
        if reported is not None and csv_net != int(reported):
            result.mismatch = (f"{SETTINGS.platform} visar netto {reported / 100:.2f} USD, "
                               f"CSV-filen ger {csv_net / 100:.2f} USD (avvikelse i underlaget)")
            source = f"pilot:reconcile:{initiative}:{file_sha[:16]}:{reported}"
            incident = next((i for i in system.incidents.all() if i.source == source), None)
            if incident is None:
                incident = system.incidents.open(founder, f"Avstämning mot {SETTINGS.platform} stämmer inte (ER-23)",
                                                 source=source)
            result.incident_id = incident.incident_id
        system.audit.append(founder, "pilot.sales_imported", {
            "initiative": initiative, "sales": result.sales, "refunds": result.refunds,
            "duplicates": result.duplicates, "net_minor": result.net_minor, "currency": CURRENCY,
            "reconciled_ledger_net_minor": ledger_net, "mismatch": result.mismatch})
    return result


def check_stops(system, founder: str, initiative: str, since: str | None, today: str) -> list[str]:
    """Stop-loss och stoppkriterier på riktiga data. Slår något till sätts skyddat läge (inga nya utgifter)."""
    from ..ledger import EntryType, Status

    reasons = [t.describe() for t in system.stoploss.evaluate()]
    entries = [e for e in system.ledger.entries(CURRENCY) if e.initiative == initiative and e.status is Status.SETTLED]
    sales = sum(1 for e in entries if e.entry_type is EntryType.REVENUE)
    refunds = sum(1 for e in entries if e.entry_type is EntryType.REFUND)
    if since is not None and sales == 0 and (date.fromisoformat(today) - date.fromisoformat(since[:10])).days >= NO_SALE_DAYS:
        reasons.append(f"ingen försäljning på {NO_SALE_DAYS} dagar sedan godkännandet ({since[:10]})")
    num, den = REFUND_STOP_RATIO
    if sales >= den and refunds * den >= sales * num:
        reasons.append(f"{refunds} återbetalningar på {sales} försäljningar")
    if reasons and not system.protected.state().protected:
        system.protected.report_incident(founder, f"pilotens stoppregel för {initiative}: " + "; ".join(reasons))
    return reasons


def stop_advice(reasons: list[str]) -> str:
    if not reasons:
        return "Inga stoppregler har slagit till. Fortsätt och importera försäljningen varje vecka."
    return ("STOPP: " + "; ".join(reasons) + ". Nya utgifter är spärrade (skyddat läge). "
            "Rekommendation: avpublicera produkten på plattformen för hand.")
