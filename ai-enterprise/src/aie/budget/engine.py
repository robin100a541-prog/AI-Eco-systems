"""Budgetmotorn (Fas 4b, ER-03, ER-17, ER-22): kontrollen före varje ekonomisk handling.

`BudgetEngine.record_spend()` låser, kontrollerar och bokför en ny utgift atomärt.
En pending-post reserverar pengar före extern verkställighet; settled används för simulerade kostnader.
`check()` är endast rådgivande och varken reserverar kapital eller förbrukar godkännanden.

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
   I kapitalläget (D-047, rättat enligt D-051) har varje departement ett **tak**:

       bas   = insatt kapital − reserv + resultatdel
       tak   = andel × bas (högst MAX_DEPARTMENT_BUDGET)
       kvar  = tak − departementets egna utgifter, men aldrig mer än det disponibla kapitalet

   - Insatt kapital är genomförda `capital_in` minus `capital_out`, inte en konstant.
   - Resultatdelen är resultatet efter reserverad skatt och *före* departementens egna utgifter (de
     räknas redan mot taken). Vid vinst räknas bara `REINVESTMENT_POLICY` procent av den, så att resten
     aldrig kan spenderas. Vid förlust räknas hela förlusten, och basen krymper.
   - Basen är aldrig större än det disponibla kapitalet med departementens utgifter tillagda.
   Upprepade kontroller kan därför aldrig flytta taket: det beror inte på hur mycket som redan har
   spenderats. Plattformsavgifter räknas inte som departementets utgifter.
6. **Åtaganden:** väntade utgifter plus beloppet får inte överstiga departementets `max_commitment`
   eller hela företagets `MAX_COMMITTED_CAPITAL` (§23).
7. **Godkännande:** över `HUMAN_APPROVAL_THRESHOLD`, eller om gränsen saknas, krävs en grundare (D-049)
   (D-019). Det blockerar inte, men svaret är nej tills godkännandet finns (ER-14).

8. **Uppdelade köp** (Fas 4d, ER-04, §5): små utgifter i samma initiativ inom sju dagar som
   tillsammans passerar `HUMAN_APPROVAL_THRESHOLD` eller `MAX_SINGLE_TRANSACTION` flaggas. Utgiften
   behandlas då som hela summan och kräver en grundare (D-028, D-049). Den revideras med flaggan.
9. **Skyddad reserv** (Fas 4c, §5, ER-05): beloppet får inte vara större än det disponibla kapitalet,
   alltså likvida medel minus `MINIMUM_RESERVE` minus redan åtagna kostnader (`capital.py`).

10. **Spärrar** (Fas 4e, `gates=`): en aktiv stop-loss (ER-13) blockerar nya åtaganden i sitt område.
    Kan en spärr inte avgöra blir svaret nej (§59).

Saknas en gräns som behövs blockeras handlingen (ER-02). Varje kontroll skrivs till revisionsloggen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from ..audit import AuditLog
from ..config.models import RiskLimits
from ..ledger import Approval, EntryDraft, EntryType, Ledger, LedgerError, Status, compute_result
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
        gates: tuple = (),
        tax=None,
        approvals=None,
        initiatives=None,
    ) -> None:
        """`gates`: spärrar med `spend_block_reasons(request) -> list[str]`, t.ex. stop-loss (ER-13).
        `tax`: en `TaxEngine`; den reserverade skatten räknas då som åtagande (ER-19, D-032)."""
        self._clock = clock
        self._tax = tax
        self._approvals = approvals  # SpendApprovals (F5, D-053): godkända utgifter över tröskeln
        # F6, D-054: initiativregistret (PR 4). `spend_block_reason(department, initiative) -> str | None`.
        # Utan register (None) görs ingen initiativkontroll; när registret kopplas in gäller den direkt.
        self._initiatives = initiatives
        self._gates = tuple(gates)
        self._ledger = ledger
        self._limits = limits
        self._budgets = dict(budgets)
        self._audit = audit
        self._capital_mode = any(b.capital_based for b in self._budgets.values())
        # D-047: i kapitalläget är plattformsavgifter försäljningskostnader, inte departementets utgifter
        self._spend_types = frozenset({EntryType.COST}) if self._capital_mode else _SPEND_TYPES

    def check(self, actor: str, request: SpendRequest, approval_id: int | None = None) -> BudgetCheck:
        """`approval_id`: ett godkännande från en grundare (F5, D-053). Det ersätter bara kravet på en
        grundare; alla andra gränser gäller. Kontroll är rådgivande; record_spend förbrukar atomärt."""
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
            if budget.capital_based:
                available = self._available(budget)
                if amount > available:
                    blocked.append(
                        f"budgeten överskrids: {amount} > kvar {available} {limits.currency} av departementets tak "
                        f"({budget.share_percent} % av basen {self.capital_base()}, D-047, D-051, §52)"
                    )
            elif spent + amount > budget.budget_minor:
                blocked.append(
                    f"budgeten överskrids: {spent} + {amount} > {budget.budget_minor} {limits.currency} (§52)"
                )
            if committed + amount > budget.max_commitment_minor:
                blocked.append(
                    f"departementets åtaganden överskrids: {committed} + {amount} > {budget.max_commitment_minor}"
                )
        if self._initiatives is not None and isinstance(r.initiative, str) and r.initiative.strip():
            try:
                reason = self._initiatives.spend_block_reason(r.department, r.initiative)
            except Exception as exc:  # noqa: BLE001 — kan registret inte svara blir svaret nej (§59)
                reason = f"initiativregistret kunde inte avgöra ({type(exc).__name__}); nekas"
            if reason:
                blocked.append(reason)
        if r.risk_class is Risk.CRITICAL:
            blocked.append("riskklass critical tillåts aldrig (§24)")
        blocked += self._hard_limits(amount, limits)
        tax_reserved = self._tax.reserved_minor(limits.currency) if self._tax is not None else None
        position = capital_position(self._ledger.entries(limits.currency), limits, tax_reserved)
        if position.reserve_minor is None:
            blocked.append("MINIMUM_RESERVE saknas; den skyddade reserven kan inte skyddas (ER-02, ER-05)")
        elif amount > position.disposable_minor:
            blocked.append(
                f"den skyddade reserven skulle användas: {amount} > disponibelt {position.disposable_minor} "
                f"(likvida {position.liquid_minor} − reserv {position.reserve_minor} − åtaget {position.committed_minor}, §5, ER-05)"
            )
        for gate in self._gates:  # 10. stop-loss, nödstopp och skyddat driftläge (Fas 4e)
            try:
                blocked += gate.spend_block_reasons(r)
            except Exception as exc:  # noqa: BLE001 — kan spärren inte avgöra blir svaret nej (§59)
                blocked.append(f"spärren {type(gate).__name__} kunde inte avgöra ({type(exc).__name__}); nekas")
        required = self._required_approvals(amount)
        flags = self._split_flags(r, amount) if amount_ok else []
        if flags:
            required = 1  # behandlas som hela summan: över tröskeln ⇒ en grundare (D-049, ER-04)
        if approval_id is not None:
            if self._approvals is None:
                blocked.append("godkännanden för utgifter är inte kopplade till budgetmotorn (D-053)")
            else:
                problems = self._approvals.problems(approval_id, r, self._clock())
                blocked += problems
                if not problems:
                    required = 0  # en grundare har godkänt just den här utgiften (D-049)
        result = BudgetCheck(
            not blocked and required == 0,
            tuple(blocked),
            required,
            spent,
            committed,
            (self._available(budget) if budget.capital_based else budget.budget_minor) if budget else None,
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
                "approval_id": approval_id,
            },
        )
        return result

    def record_spend(self, actor: str, request: SpendRequest, draft: EntryDraft, *,
                     writer: str | None = None, approval_id: int | None = None):
        """Atomically check, consume approval and record a COST (pending reserves funds).

        `check()` is advisory. All new spending must use this command before external
        execution. The ledger still accepts historical facts independently.
        """
        if (draft.department, draft.initiative, draft.amount_minor, draft.currency, draft.entry_type) != (
                request.department, request.initiative, request.amount_minor, request.currency, EntryType.COST):
            raise LedgerError("utgiftens bokföringsunderlag stämmer inte med budgetförfrågan")
        evidence = tuple(draft.evidence)
        if approval_id is not None:
            evidence += (f"approval:spend-{approval_id}",)
        draft = replace(draft, approval=Approval.APPROVED if approval_id is not None else Approval.NOT_REQUIRED,
                        evidence=evidence)
        try:
            with self._ledger._db.transaction():
                existing = self._ledger._by_key(draft.idempotency_key)
                if existing is not None:
                    return self._ledger.record(writer or actor, draft)  # verify replay, do not spend again
                checked = self.check(actor, request, approval_id)
                if not checked.allowed:
                    raise BudgetBlocked(checked)
                if approval_id is not None and not self._approvals.consume(approval_id, actor, draft.idempotency_key):
                    raise BudgetBlocked(replace(checked, allowed=False, blocked=("godkännandet är redan förbrukat",)))
                return self._ledger.record(writer or actor, draft)
        except BudgetBlocked as exc:
            # The denied transaction rolled back; retain the refusal outside it.
            self._audit.append(actor, "budget.blocked", {"reference": draft.idempotency_key,
                                                        "reasons": list(exc.check.blocked)})
            raise

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
            and e.entry_type in self._spend_types
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
        # F6, D-054: samma departement samma dag, oavsett initiativnamn. Annars kan en gräns kringgås
        # genom att varje liten utgift får ett nytt initiativnamn.
        today = self._clock().date()
        same_day = [
            e for e in self._ledger.entries(self._limits.currency)
            if e.department == r.department
            and e.entry_type in self._spend_types
            and e.status in (Status.PENDING, Status.SETTLED)
            and e.approval is Approval.NOT_REQUIRED
            and datetime.fromisoformat(e.recorded_at).astimezone(UTC).date() == today
        ]
        day_total = sum(e.amount_minor for e in same_day) + amount
        threshold = self._limits.human_approval_threshold
        names = {e.initiative for e in same_day} | {r.initiative}
        if threshold is not None and same_day and amount <= threshold.amount_minor < day_total and len(names) > 1:
            flags.append(
                f"möjlig uppdelning: {len(same_day) + 1} utgifter i departementet {r.department!r} i dag, i "
                f"{len(names)} olika initiativ, blir tillsammans {day_total} > HUMAN_APPROVAL_THRESHOLD "
                f"{threshold.amount_minor} (ER-04, D-054)"
            )
        return flags

    def _required_approvals(self, amount: int) -> int:
        threshold = self._limits.human_approval_threshold
        if threshold is None or amount > threshold.amount_minor:
            return 1  # D-019, D-049: en grundare; en saknad gräns räknas som över (ER-02)
        return 0

    def _departments_in_ledger(self) -> set[str]:
        return {e.department for e in self._ledger.entries()}

    def usage(self, department: str) -> tuple[int, int | None]:
        """(utgifter hittills, vad som återstår att använda nu) för departementet. None = ingen budget.

        Fast läge: budget minus utgifter. Kapitalläge (D-047, D-051): taket minus egna utgifter, högst
        det disponibla. Ren läsning; inget revideras.
        """
        budget = self._budgets.get(department)
        spent = self._usage(department, self._limits.currency)[0]
        if budget is None:
            return spent, None
        if budget.capital_based:
            return spent, self._available(budget)
        return spent, max(0, budget.budget_minor - spent)

    def capital_base(self) -> int:
        """D-051: basen som departementens tak räknas från. Se modulens docstring, punkt 5."""
        limits, currency = self._limits, self._limits.currency
        entries = self._ledger.entries(currency)
        if limits.minimum_reserve is None:
            return 0  # ER-02: utan reserv kan inget disponeras
        deposited = sum(e.amount_minor if e.entry_type is EntryType.CAPITAL_IN else -e.amount_minor
                        for e in entries if e.status is Status.SETTLED
                        and e.entry_type in (EntryType.CAPITAL_IN, EntryType.CAPITAL_OUT))
        spent_by_departments = sum(e.amount_minor for e in entries if e.entry_type in self._spend_types
                                   and e.status in (Status.PENDING, Status.SETTLED))
        # Hela skatteskulden räknas av, även det som redan är betalt: betalningen har minskat kassan,
        # men den har inte gjort vinsten större (D-052). Det disponibla räknas med det som är kvar att betala.
        tax = self._tax.liability_minor(currency) if self._tax is not None else 0
        result = compute_result(entries, currency).net_minor + spent_by_departments - tax
        if result > 0:
            policy = limits.reinvestment_policy
            part = int(result * policy) // 100 if policy is not None else 0  # ER-02: saknas ⇒ inget återinvesteras
        else:
            part = result  # hela förlusten
        base = deposited - limits.minimum_reserve.amount_minor + part
        outstanding = self._tax.reserved_minor(currency) if self._tax is not None else None
        position = capital_position(entries, limits, outstanding)
        return max(0, min(base, position.disposable_minor + spent_by_departments))

    def department_cap(self, budget) -> int:
        """D-051: departementets tak = andel × bas, högst MAX_DEPARTMENT_BUDGET."""
        cap = self._limits.max_department_budget
        if cap is None:
            return 0  # ER-02
        return min(self.capital_base() * budget.share_percent // 100, cap.amount_minor)

    def _available(self, budget) -> int:
        """D-051: taket minus departementets egna utgifter, aldrig mer än det disponibla kapitalet."""
        currency = self._limits.currency
        tax = self._tax.reserved_minor(currency) if self._tax is not None else None
        disposable = capital_position(self._ledger.entries(currency), self._limits, tax).disposable_minor
        own = self._usage(budget.department, currency)[0]
        return max(0, min(self.department_cap(budget) - own, disposable))

    def _usage(self, department: str, currency: str) -> tuple[int, int]:
        """(utgifter, väntade utgifter) för departementet. Korrigeringar räknas med sitt tecken."""
        spent = committed = 0
        for e in self._ledger.entries(currency):
            if e.department != department or e.entry_type not in self._spend_types:
                continue
            if e.status in (Status.PENDING, Status.SETTLED):
                spent += e.amount_minor
            if e.status is Status.PENDING:
                committed += e.amount_minor
        return spent, committed
