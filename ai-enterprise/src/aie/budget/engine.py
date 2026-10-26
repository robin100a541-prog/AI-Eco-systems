"""Budgetmotorn (Fas 4b, ER-03, ER-17, ER-22): kontrollen före varje ekonomisk handling.

`BudgetEngine.check()` svarar på frågan "får den här utgiften göras nu?" innan något händer.
Alla skäl samlas, och svaret är ja bara när inget blockerar och inget godkännande behövs:

1. **Belopp och valuta:** heltal > 0 i riskgränsernas valuta (ER-01, ER-15).
2. **Departementet** måste ha en budget i `config/budgets.toml`; saknas den blockeras allt (ER-02).
3. **`API_SPEND`** är spärrad tills Tax Engine kan visa realiserad nettovinst *efter skatt* (ER-22,
   D-009). Tax Engine finns inte än (4f), så kategorin blockeras alltid.
4. **MAX_SINGLE_TRANSACTION** och **riskklass:** över gränsen, över departementets riskutrymme
   eller `critical` blockeras (§24, §25).
5. **Budget:** departementets utgifter i ledgern (kostnader och avgifter, väntade och genomförda,
   med korrigeringar) plus beloppet får inte överstiga budgeten (§52: budgetöverskridanden blockeras).
6. **Åtaganden:** väntade utgifter plus beloppet får inte överstiga departementets `max_commitment`
   eller hela företagets `MAX_COMMITTED_CAPITAL` (§23).
7. **Godkännande:** över `HUMAN_APPROVAL_THRESHOLD`, eller om gränsen saknas, krävs båda grundarna
   (D-019). Det blockerar inte, men svaret är nej tills godkännandet finns (ER-14).

8. **Uppdelade köp** (Fas 4d, ER-04, §5): små utgifter i samma initiativ inom sju dagar som
   tillsammans passerar `HUMAN_APPROVAL_THRESHOLD` eller `MAX_SINGLE_TRANSACTION` flaggas. Utgiften
   behandlas då som hela summan och kräver båda grundarna (D-028). Den revideras med flaggan.
9. **Skyddad reserv** (Fas 4c, §5, ER-05): beloppet får inte vara större än det disponibla kapitalet,
   alltså likvida medel minus `MINIMUM_RESERVE` minus redan åtagna kostnader (`capital.py`).

Saknas en gräns som behövs blockeras handlingen (ER-02). Varje kontroll skrivs till revisionsloggen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..audit import AuditLog
from ..config.models import RiskLimits
from ..ledger import Approval, EntryType, Ledger, Status
from .capital import capital_position
from .config import Budget, Risk

API_SPEND = "API_SPEND"
SPLIT_WINDOW = timedelta(days=7)  # D-028: tidsfönstret för uppdelningsdetektering (ER-04)


def _utc_now() -> datetime:
    return datetime.now(UTC)

_SPEND_TYPES = frozenset({EntryType.COST, EntryType.FEE})


_RANK = {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2, Risk.CRITICAL: 3}


@dataclass(frozen=True, slots=True)
class SpendRequest:
    department: str
    amount_minor: int
    currency: str
    initiative: str
    risk_class: Risk
    category: str = "OPERATIONS"


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    allowed: bool
    blocked: tuple[str, ...]  # skäl som stoppar utgiften helt
    required_approvals: (
        int  # 0, 1 eller 2 grundare (D-019); > 0 betyder nej tills godkänt
    )
    spent_minor: int  # departementets utgifter före den här
    committed_minor: int  # departementets väntade utgifter före den här
    budget_minor: int | None
    flags: tuple[str, ...] = ()  # misstankar som kräver grundarna, t.ex. uppdelade köp (ER-04)

    def describe(self) -> str:
        if self.allowed:
            return "tillåten"
        parts = [*self.blocked, *self.flags]
        if self.required_approvals:
            parts.append(f"kräver {self.required_approvals} grundare (D-019)")
        return "nej: " + "; ".join(parts)


class BudgetBlocked(PermissionError):
    def __init__(self, check: BudgetCheck) -> None:
        self.check = check
        super().__init__(f"utgiften stoppas av budgetmotorn: {check.describe()}")


class BudgetEngine:
    def __init__(
        self,
        ledger: Ledger,
        limits: RiskLimits,
        budgets: dict[str, Budget],
        audit: AuditLog,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._clock = clock
        self._ledger = ledger
        self._limits = limits
        self._budgets = dict(budgets)
        self._audit = audit

    def check(self, actor: str, request: SpendRequest) -> BudgetCheck:
        blocked: list[str] = []
        r, limits = request, self._limits
        amount_ok = (
            isinstance(r.amount_minor, int)
            and not isinstance(r.amount_minor, bool)
            and r.amount_minor > 0
        )
        if not amount_ok:
            blocked.append("beloppet måste vara ett heltal > 0 i minsta enhet (ER-01)")
        if r.currency != limits.currency:
            blocked.append(
                f"valutan {r.currency!r} är inte riskgränsernas {limits.currency!r} (ER-15)"
            )
        if not isinstance(r.initiative, str) or not r.initiative.strip():
            blocked.append("affärsinitiativ saknas (§40)")
        if not isinstance(r.risk_class, Risk):
            blocked.append("okänd riskklass (§24)")
        amount = r.amount_minor if amount_ok else 0
        budget = self._budgets.get(r.department)
        spent, committed = self._usage(r.department, limits.currency)
        if r.category == API_SPEND:
            blocked.append(
                "API_SPEND är spärrad tills Tax Engine visar realiserad nettovinst efter skatt (ER-22, D-009)"
            )
        if budget is None:
            blocked.append(
                f"departementet {r.department!r} har ingen budget i budgets.toml (ER-02, ER-17)"
            )
        else:
            if (
                isinstance(r.risk_class, Risk)
                and _RANK[r.risk_class] > _RANK[budget.risk_room]
            ):
                blocked.append(
                    f"riskklass {r.risk_class.value} är över departementets riskutrymme {budget.risk_room.value}"
                )
            if spent + amount > budget.budget_minor:
                blocked.append(
                    f"budgeten överskrids: {spent} + {amount} > {budget.budget_minor} {limits.currency} (§52)"
                )
            if committed + amount > budget.max_commitment_minor:
                blocked.append(
                    f"departementets åtaganden överskrids: {committed} + {amount} > {budget.max_commitment_minor}"
                )
        if r.risk_class is Risk.CRITICAL:
            blocked.append("riskklass critical tillåts aldrig (§24)")
        blocked += self._hard_limits(amount, limits)
        position = capital_position(self._ledger.entries(limits.currency), limits)
        if position.reserve_minor is None:
            blocked.append("MINIMUM_RESERVE saknas; den skyddade reserven kan inte skyddas (ER-02, ER-05)")
        elif amount > position.disposable_minor:
            blocked.append(
                f"den skyddade reserven skulle användas: {amount} > disponibelt {position.disposable_minor} "
                f"(likvida {position.liquid_minor} − reserv {position.reserve_minor} − åtaget {position.committed_minor}, §5, ER-05)"
            )
        required = self._required_approvals(amount)
        flags = self._split_flags(r, amount) if amount_ok else []
        if flags:
            required = 2  # behandlas som hela summan: över tröskeln ⇒ båda grundarna (D-019, ER-04)
        result = BudgetCheck(
            not blocked and required == 0,
            tuple(blocked),
            required,
            spent,
            committed,
            budget.budget_minor if budget else None,
            tuple(flags),
        )
        self._audit.append(
            actor,
            "budget.allowed" if result.allowed else "budget.blocked",
            {
                "department": r.department,
                "amount_minor": amount,
                "currency": r.currency,
                "initiative": r.initiative,
                "category": r.category,
                "reasons": list(result.blocked),
                "flags": list(result.flags),
                "required_approvals": required,
            },
        )
        return result

    def require(self, actor: str, request: SpendRequest) -> BudgetCheck:
        """Som `check`, men kastar `BudgetBlocked` vid nej. Anropas före varje ekonomisk handling."""
        result = self.check(actor, request)
        if not result.allowed:
            raise BudgetBlocked(result)
        return result

    # --- Internt -----------------------------------------------------------------------------

    def _hard_limits(self, amount: int, limits: RiskLimits) -> list[str]:
        out: list[str] = []
        single = limits.max_single_transaction
        if single is None:
            out.append("MAX_SINGLE_TRANSACTION saknas (ER-02)")
        elif amount > single.amount_minor:
            out.append(
                f"över MAX_SINGLE_TRANSACTION ({amount} > {single.amount_minor})"
            )
        committed_cap = limits.max_committed_capital
        if committed_cap is None:
            out.append("MAX_COMMITTED_CAPITAL saknas (ER-02)")
        else:
            total = sum(
                self._usage(d, limits.currency)[1]
                for d in self._departments_in_ledger()
            )
            if total + amount > committed_cap.amount_minor:
                out.append(
                    f"företagets åtaganden överskrids: {total} + {amount} > {committed_cap.amount_minor} (§23)"
                )
        return out

    def _split_flags(self, r: SpendRequest, amount: int) -> list[str]:
        """ER-04, §5: små utgifter i samma initiativ inom SPLIT_WINDOW som tillsammans passerar en gräns.

        Bara poster som inte behövde godkännande räknas; en utgift som grundarna redan har godkänt
        kan inte vara ett försök att slippa godkännande. Väntade och genomförda räknas.
        """
        since = self._clock() - SPLIT_WINDOW
        earlier = [
            e for e in self._ledger.entries(self._limits.currency)
            if e.initiative == r.initiative
            and e.entry_type in _SPEND_TYPES
            and e.status in (Status.PENDING, Status.SETTLED)
            and e.approval is Approval.NOT_REQUIRED
            and datetime.fromisoformat(e.recorded_at) >= since
        ]
        total = sum(e.amount_minor for e in earlier) + amount
        flags: list[str] = []
        for name, limit in (
            ("HUMAN_APPROVAL_THRESHOLD", self._limits.human_approval_threshold),
            ("MAX_SINGLE_TRANSACTION", self._limits.max_single_transaction),
        ):
            if limit is not None and earlier and amount <= limit.amount_minor < total:
                flags.append(
                    f"möjlig uppdelning: {len(earlier) + 1} utgifter i {r.initiative!r} på {SPLIT_WINDOW.days} dagar "
                    f"blir tillsammans {total} > {name} {limit.amount_minor} (ER-04)"
                )
        return flags

    def _required_approvals(self, amount: int) -> int:
        threshold = self._limits.human_approval_threshold
        if threshold is None or amount > threshold.amount_minor:
            return 2  # D-019 p. 2; en saknad gräns räknas som över (ER-02)
        return 0

    def _departments_in_ledger(self) -> set[str]:
        return {e.department for e in self._ledger.entries()}

    def _usage(self, department: str, currency: str) -> tuple[int, int]:
        """(utgifter, väntade utgifter) för departementet. Korrigeringar räknas med sitt tecken."""
        spent = committed = 0
        for e in self._ledger.entries(currency):
            if e.department != department or e.entry_type not in _SPEND_TYPES:
                continue
            if e.status in (Status.PENDING, Status.SETTLED):
                spent += e.amount_minor
            if e.status is Status.PENDING:
                committed += e.amount_minor
        return spent, committed
