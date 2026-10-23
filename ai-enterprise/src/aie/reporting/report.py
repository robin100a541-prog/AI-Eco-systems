"""Standardiserat rapportformat (FR-08, konstitutionen §7).

En rapport består av påståenden (`Claim`), och varje påstående har exakt en av de tio
kategorierna i §7. Det gör det omöjligt att blanda ihop "vi tror" med "det har hänt", eller
"omsättning" med "vinst".

Regler som kontrolleras när rapporten skapas (`ReportError` vid fel, alla fel på en gång):
- Från och med `DONE` krävs underlag (§7: inget påstående om slutfört arbete utan bevis).
- `BOOKED`, `REALIZED_REVENUE` och `REALIZED_NET_PROFIT` måste peka på ledgern
  (`ledger:<id>`). En realiserad siffra räknas från bokförda poster, inte från en
  sammanfattning (ER-09, ER-11).
- Belopp får bara anges för `FORECAST`, `BOOKED`, `REALIZED_REVENUE` och
  `REALIZED_NET_PROFIT`. För de tre sista är beloppet obligatoriskt. Belopp är heltal i
  minsta enhet plus valuta (D-006).
- `REALIZED_NET_PROFIT` kan vara negativ (förlust). Övriga belopp kan inte vara negativa.
- Alla belopp i en rapport har samma valuta. SIM och verkliga pengar blandas aldrig (ER-15).

`to_dict`/`from_dict` ger ren JSON, så att en rapport kan sparas i audit-loggen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..config import Money


class ClaimKind(str, Enum):
    HYPOTHESIS = "hypothesis"  # hypotes
    FORECAST = "forecast"  # prognos
    PLAN = "plan"  # plan
    ATTEMPT = "attempt"  # försök
    DONE = "done"  # genomförd åtgärd
    OBSERVED = "observed"  # observerat resultat
    VERIFIED = "verified"  # verifierat resultat
    BOOKED = "booked"  # bokförd transaktion
    REALIZED_REVENUE = "realized_revenue"  # realiserad intäkt
    REALIZED_NET_PROFIT = "realized_net_profit"  # realiserad nettovinst


K = ClaimKind
NEEDS_EVIDENCE = frozenset({K.DONE, K.OBSERVED, K.VERIFIED, K.BOOKED, K.REALIZED_REVENUE, K.REALIZED_NET_PROFIT})
NEEDS_LEDGER = frozenset({K.BOOKED, K.REALIZED_REVENUE, K.REALIZED_NET_PROFIT})
MAY_HAVE_AMOUNT = frozenset({K.FORECAST, *NEEDS_LEDGER})
NEEDS_AMOUNT = NEEDS_LEDGER
MAY_BE_NEGATIVE = frozenset({K.REALIZED_NET_PROFIT})

# Underlag pekar på något som går att kontrollera: ledger:<id>, task:<id>, audit:<seq>, file:<sökväg>, url:<adress>
_EVIDENCE = re.compile(r"(ledger|task|audit|file|url):\S+")


class ReportError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Rapporten är ogiltig:\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass(frozen=True, slots=True)
class Claim:
    kind: ClaimKind
    statement: str
    evidence: tuple[str, ...] = ()
    amount: Money | None = None


@dataclass(frozen=True, slots=True)
class Report:
    author: str  # agent-ID
    title: str
    claims: tuple[Claim, ...]
    task_id: int | None = None

    def __post_init__(self) -> None:
        errors = validate(self)
        if errors:
            raise ReportError(errors)

    def by_kind(self, kind: ClaimKind) -> tuple[Claim, ...]:
        return tuple(c for c in self.claims if c.kind is kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "title": self.title,
            "task_id": self.task_id,
            "claims": [
                {
                    "kind": c.kind.value,
                    "statement": c.statement,
                    "evidence": list(c.evidence),
                    "amount": None if c.amount is None
                    else {"amount_minor": c.amount.amount_minor, "currency": c.amount.currency},
                }
                for c in self.claims
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Report:
        claims = tuple(
            Claim(
                kind=ClaimKind(c["kind"]),
                statement=c["statement"],
                evidence=tuple(c.get("evidence", ())),
                amount=None if c.get("amount") is None else Money(**c["amount"]),
            )
            for c in data["claims"]
        )
        return cls(author=data["author"], title=data["title"], claims=claims, task_id=data.get("task_id"))


def validate(report: Report) -> list[str]:
    errors: list[str] = []
    if not report.author.strip():
        errors.append("author saknas")
    if not report.title.strip():
        errors.append("title saknas")
    if not report.claims:
        errors.append("rapporten har inga påståenden")

    currencies: set[str] = set()
    for i, claim in enumerate(report.claims, start=1):
        if not isinstance(claim.kind, ClaimKind):
            errors.append(f"påstående {i}: okänd kategori {claim.kind!r}")
            continue
        where = f"påstående {i} ({claim.kind.value})"
        if not claim.statement.strip():
            errors.append(f"{where}: texten saknas")
        bad = [e for e in claim.evidence if not _EVIDENCE.fullmatch(e)]
        if bad:
            errors.append(f"{where}: ogiltigt underlag {bad} (använd ledger:, task:, audit:, file: eller url:)")
        if claim.kind in NEEDS_EVIDENCE and not claim.evidence:
            errors.append(f"{where}: underlag krävs (§7)")
        if claim.kind in NEEDS_LEDGER and not any(e.startswith("ledger:") for e in claim.evidence):
            errors.append(f"{where}: måste peka på en ledgerpost (ledger:<id>) (ER-09)")
        if claim.amount is not None:
            if claim.kind not in MAY_HAVE_AMOUNT:
                errors.append(f"{where}: belopp får bara anges för prognos, bokfört eller realiserat")
            elif isinstance(claim.amount.amount_minor, bool) or not isinstance(claim.amount.amount_minor, int):
                errors.append(f"{where}: belopp måste vara heltal i minsta enhet (D-006)")
            elif claim.amount.amount_minor < 0 and claim.kind not in MAY_BE_NEGATIVE:
                errors.append(f"{where}: beloppet kan inte vara negativt")
            currencies.add(claim.amount.currency)
        elif claim.kind in NEEDS_AMOUNT:
            errors.append(f"{where}: belopp krävs")
    if len(currencies) > 1:
        errors.append(f"blandade valutor {sorted(currencies)}; en rapport har en valuta (ER-15)")
    return errors
