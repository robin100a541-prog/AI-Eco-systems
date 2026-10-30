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
    """(beslutets nummer, tidpunkt) när piloten godkändes, eller None."""
    row = db.connection.execute(
        "SELECT decision_id, decided_at FROM decisions WHERE chosen_action LIKE ? ORDER BY decision_id DESC LIMIT 1",
        (f"Starta piloten {initiative}:%",)).fetchone()
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


def _usd_cents(text: str) -> int:
    clean = text.strip().replace("$", "").replace(",", "")
    try:
        value = float(clean or "0")
    except ValueError as exc:
        raise PilotError(f"ogiltigt belopp {text!r}") from exc
    if value < 0:
        raise PilotError(f"negativt belopp {text!r}")
    return round(value * 100)


def parse_sales_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise PilotError("CSV-filen är tom")
    cols = {k: _column(reader.fieldnames, k) for k in ("id", "date", "price", "fee")}
    refunded = next((h for h in reader.fieldnames if h.strip().lower() in _ALIASES["refunded"]), None)
    rows = []
    for n, r in enumerate(reader, 2):
        sale_id = (r.get(cols["id"]) or "").strip()
        if not sale_id:
            raise PilotError(f"rad {n}: försäljnings-ID saknas")
        day = (r.get(cols["date"]) or "").strip()[:10]
        try:
            date.fromisoformat(day)
        except ValueError as exc:
            raise PilotError(f"rad {n}: ogiltigt datum {day!r}") from exc
        is_refund = (r.get(refunded) or "").strip().lower() in ("true", "yes", "ja", "1") if refunded else False
        rows.append({"id": sale_id, "day": day, "price": _usd_cents(r[cols["price"]]),
                     "fee": _usd_cents(r[cols["fee"]]), "refunded": is_refund})
    return rows


def import_sales(system, founder: str, initiative: str, text: str, usd_sek: float,
                 reported_net_usd: float | None) -> ImportResult:
    """Bokför plattformens försäljning i pilotens ledger (SEK) och stämmer av mot plattformens totalsumma."""
    from ..ledger import Approval, EntryDraft, EntryType, Status

    if system.currency == "SIM":
        raise PilotError("riktig försäljning bokförs aldrig i en SIM-databas (ER-15)")
    if usd_sek <= 0:
        raise PilotError("växelkursen måste vara större än 0")
    approved = approval(system.db, initiative)
    if approved is None:
        raise PilotError(f"piloten {initiative} är inte godkänd; kör `aie pilot prepare` och `aie pilot approve` först")
    rows = parse_sales_csv(text)
    file_sha = hashlib.sha256(text.encode()).hexdigest()
    result, seen = ImportResult(), set()
    sek = lambda cents: round(cents * usd_sek)  # noqa: E731
    known = {e.external_id for e in system.ledger.entries(CURRENCY) if e.external_id}
    for row in rows:
        key = f"{SETTINGS.platform_key}:{row['id']}"
        if key in seen or f"{key}:sale" in known:
            result.duplicates += 1
            continue
        seen.add(key)
        evidence = (f"file:{SETTINGS.platform_key}-csv/{file_sha[:16]}", f"external:kurs-usd-sek/{usd_sek}",
                    f"decision:{approved[0]}")
        posts = [("sale", EntryType.REVENUE, sek(row["price"])), ("fee", EntryType.FEE, sek(row["fee"]))]
        if row["refunded"]:
            posts.append(("refund", EntryType.REFUND, sek(row["price"])))
        for suffix, kind, amount in posts:
            if amount == 0:
                continue
            system.ledger.record(founder, EntryDraft(
                f"{key}:{suffix}", "research", amount, CURRENCY, kind, initiative, Approval.APPROVED, evidence,
                external_id=f"{key}:{suffix}", status=Status.SETTLED, note=f"{SETTINGS.platform} {row['day']}"))
        result.sales += 1
        result.gross_minor += sek(row["price"])
        result.fees_minor += sek(row["fee"])
        if row["refunded"]:
            result.refunds += 1
            result.refunds_minor += sek(row["price"])
    if reported_net_usd is not None:
        expected = round(reported_net_usd * 100)
        unique = {r["id"]: r for r in rows}.values()
        csv_net = sum(r["price"] - r["fee"] - (r["price"] if r["refunded"] else 0) for r in unique)
        if csv_net != expected:
            result.mismatch = (f"{SETTINGS.platform} visar netto {expected / 100:.2f} USD, CSV-filen ger {csv_net / 100:.2f} USD "
                               f"(skillnad {(csv_net - expected) / 100:+.2f} USD)")
            incident = system.incidents.open(founder, f"Avstämning mot {SETTINGS.platform} stämmer inte (ER-23)",
                                             source=f"pilot:reconcile:{file_sha[:16]}")
            result.incident_id = incident.incident_id
    system.audit.append(founder, "pilot.sales_imported", {
        "initiative": initiative, "sales": result.sales, "refunds": result.refunds, "duplicates": result.duplicates,
        "net_minor": result.net_minor, "currency": CURRENCY, "mismatch": result.mismatch})
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
