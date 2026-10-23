"""Uppgiftstypen "Utred möjlighet" (FR-25, D-011, D-025).

En ny kanal, ett verktyg, ett gratis-API, en intäktsväg eller en skatte-, villkors- eller
licensfråga utreds alltid i samma ordning:

    research ──findings──► compliance ──ok──► cfo ──estimate──► founders ──approve/reject──► closed
                              │ uncertain ⇒ tillbaka till research (osäkerhet är risk, §17)
                              └ not_ok ⇒ closed / rejected

Status följer forskningskön i `research/QUESTIONS.md`:
`open` → `unconfirmed_hypothesis` (Research har svarat, §29) → `verified` (källa och Compliance)
→ `approved` eller, för skatt, villkor och licens, `approved_rule` (grundare). Annars `rejected`.

Regler:
- **Öppna:** grundare, CEO, kontrollfunktioner och departementschefer (nivå 1–3).
- **Research:** en aktiv agent i departementet research med `research.search` lämnar
  fynd med minst en källa (`url:` eller `file:`). Fynden är alltid en obekräftad hypotes.
- **Compliance:** bedömer villkor, AI-regler, automationsregler och skatt. Osäkert räknas inte som OK.
- **CFO:** räknar fram förväntat netto efter avgifter och skatt. Beloppet kan vara negativt.
- **Grundarna:** godkänner eller avvisar. En **skattefråga** kan bara godkännas om någon
  källa är Skatteverket (`skatteverket.se`) eller en rådgivares underlag (`file:`). D-011
  säger att skattefrågor som påverkar deklarationen ska bekräftas av Skatteverket eller en rådgivare.
- Agenterna föreslår bara. Ingen här kan skapa konton, godkänna villkor eller välja skattespår (D-011).
- Varje steg sparas (append-only) och loggas i audit-loggen.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ..agents import ACTING_STATES, LEVEL_HEAD, AgentRegistry
from ..audit import AuditLog
from ..authorization import Permissions
from ..config import Money
from ..memory import Database

KINDS = ("channel", "tool", "free_api", "revenue", "tax", "terms", "license", "market")
RULE_KINDS = frozenset({"tax", "terms", "license"})  # blir regler, inte bara tillstånd att prova
_SOURCE = re.compile(r"(url|file):\S+")
_REF = re.compile(r"R-\d{2,}")


class OpportunityError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class Step:
    stage: str
    actor: str
    verdict: str
    summary: str
    sources: tuple[str, ...]
    net: Money | None
    at: str


@dataclass(frozen=True, slots=True)
class Opportunity:
    opportunity_id: int
    ref: str | None  # t.ex. "R-02" i research/QUESTIONS.md
    kind: str
    title: str
    question: str
    opened_by: str
    stage: str
    status: str
    steps: tuple[Step, ...] = ()

    @property
    def sources(self) -> tuple[str, ...]:
        seen: list[str] = []
        for step in self.steps:
            seen += [s for s in step.sources if s not in seen]
        return tuple(seen)


class OpportunityRegister:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions: Permissions,
        audit: AuditLog,
        founders: frozenset[str],
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._clock = clock

    # --- Flödet --------------------------------------------------------------------------

    def open(self, actor: str, kind: str, title: str, question: str, ref: str | None = None) -> Opportunity:
        if actor not in self._founders:
            agent = self._acting(actor)
            if self._permissions.roles[agent.role].level > LEVEL_HEAD:
                raise OpportunityError("bara grundare och nivå 1–3 öppnar ett utredningsärende")
        if kind not in KINDS:
            raise OpportunityError(f"okänd typ {kind!r} (tillåtna: {', '.join(KINDS)})")
        if not title.strip() or not question.strip():
            raise OpportunityError("titel och fråga krävs")
        if ref is not None and not _REF.fullmatch(ref):
            raise OpportunityError(f"referensen {ref!r} måste se ut som R-01 (research/QUESTIONS.md)")
        if ref is not None and self._db.connection.execute(
            "SELECT 1 FROM opportunities WHERE ref = ?", (ref,)
        ).fetchone():
            raise OpportunityError(f"{ref} utreds redan")
        with self._db.transaction() as tx:
            cursor = tx.execute(
                "INSERT INTO opportunities (ref, kind, title, question, opened_by, stage, status, opened_at) "
                "VALUES (?, ?, ?, ?, ?, 'research', 'open', ?)",
                (ref, kind, title, question, actor, self._clock()),
            )
            oid = cursor.lastrowid
        self._log("opportunity.opened", oid, actor, kind=kind, ref=ref)
        return self.get(oid)

    def submit_findings(self, actor: str, opportunity_id: int, summary: str, sources: tuple[str, ...]) -> Opportunity:
        agent = self._acting(actor)
        mandate = self._permissions.roles[agent.role]
        if agent.department != "research" or "research.search" not in mandate.tools:
            raise OpportunityError("bara Research (med research.search) lämnar fynd (D-011 steg 1)")
        self._require_sources(sources)
        return self._step(opportunity_id, "research", actor, "findings", summary, sources,
                          next_stage="compliance", status="unconfirmed_hypothesis")

    def compliance_review(
        self, actor: str, opportunity_id: int, verdict: str, summary: str, sources: tuple[str, ...] = ()
    ) -> Opportunity:
        self._require_role(actor, "compliance")
        if verdict not in ("ok", "not_ok", "uncertain"):
            raise OpportunityError("Compliance svarar ok, not_ok eller uncertain")
        if sources:
            self._require_sources(sources)
        if verdict == "ok":
            return self._step(opportunity_id, "compliance", actor, verdict, summary, sources,
                              next_stage="cfo", status="verified")
        if verdict == "uncertain":  # §17: osäkerhet är risk; Research måste ta fram mer underlag
            return self._step(opportunity_id, "compliance", actor, verdict, summary, sources,
                              next_stage="research", status="unconfirmed_hypothesis")
        return self._step(opportunity_id, "compliance", actor, verdict, summary, sources,
                          next_stage="closed", status="rejected")

    def cfo_estimate(self, actor: str, opportunity_id: int, summary: str, net: Money) -> Opportunity:
        self._require_role(actor, "cfo")
        if isinstance(net.amount_minor, bool) or not isinstance(net.amount_minor, int):
            raise OpportunityError("nettot anges som heltal i minsta enhet (D-006)")
        return self._step(opportunity_id, "cfo", actor, "estimate", summary, (), net=net,
                          next_stage="founders", status="verified")

    def founder_decision(
        self, actor: str, opportunity_id: int, approve: bool, summary: str, sources: tuple[str, ...] = ()
    ) -> Opportunity:
        if actor not in self._founders:
            raise OpportunityError("bara grundarna godkänner eller avvisar (D-011 steg 4)")
        if sources:
            self._require_sources(sources)
        opp = self._require(opportunity_id, "founders")
        if approve and opp.kind == "tax":
            all_sources = (*opp.sources, *sources)
            if not any("skatteverket.se" in s or s.startswith("file:") for s in all_sources):
                raise OpportunityError(
                    "en skattefråga godkänns bara med underlag från Skatteverket (skatteverket.se) eller en "
                    "rådgivare (file:) (D-011)"
                )
        status = ("approved_rule" if opp.kind in RULE_KINDS else "approved") if approve else "rejected"
        return self._step(opportunity_id, "founders", actor, "approve" if approve else "reject", summary, sources,
                          next_stage="closed", status=status)

    # --- Frågor --------------------------------------------------------------------------

    def get(self, opportunity_id: int) -> Opportunity | None:
        row = self._db.connection.execute(
            "SELECT opportunity_id, ref, kind, title, question, opened_by, stage, status FROM opportunities "
            "WHERE opportunity_id = ?",
            (opportunity_id,),
        ).fetchone()
        if row is None:
            return None
        steps = tuple(
            Step(stage, actor, verdict, summary, tuple(json.loads(sources)),
                 None if net is None else Money(net, currency), at)
            for stage, actor, verdict, summary, sources, net, currency, at in self._db.connection.execute(
                "SELECT stage, actor, verdict, summary, sources, net_minor, currency, at FROM opportunity_steps "
                "WHERE opportunity_id = ? ORDER BY id",
                (opportunity_id,),
            )
        )
        return Opportunity(*row, steps=steps)

    def waiting_for(self, stage: str) -> tuple[Opportunity, ...]:
        ids = [r[0] for r in self._db.connection.execute(
            "SELECT opportunity_id FROM opportunities WHERE stage = ? ORDER BY opportunity_id", (stage,))]
        return tuple(self.get(i) for i in ids)

    # --- Internt -------------------------------------------------------------------------

    def _step(
        self, opportunity_id: int, stage: str, actor: str, verdict: str, summary: str, sources: tuple[str, ...],
        next_stage: str, status: str, net: Money | None = None,
    ) -> Opportunity:
        if not summary.strip():
            raise OpportunityError("en sammanfattning krävs")
        self._require(opportunity_id, stage)
        with self._db.transaction() as tx:
            current = tx.execute("SELECT stage FROM opportunities WHERE opportunity_id = ?", (opportunity_id,)).fetchone()
            if current[0] != stage:  # någon hann före
                raise OpportunityError(f"ärendet väntar på {current[0]}, inte {stage}")
            tx.execute(
                "INSERT INTO opportunity_steps (opportunity_id, stage, actor, verdict, summary, sources, net_minor, "
                "currency, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (opportunity_id, stage, actor, verdict, summary, json.dumps(list(sources)),
                 net.amount_minor if net else None, net.currency if net else None, self._clock()),
            )
            tx.execute("UPDATE opportunities SET stage = ?, status = ? WHERE opportunity_id = ?",
                       (next_stage, status, opportunity_id))
        self._log(f"opportunity.{verdict}", opportunity_id, actor, stage=stage, next_stage=next_stage,
                  status=status, sources=list(sources))
        return self.get(opportunity_id)

    def _require(self, opportunity_id: int, stage: str) -> Opportunity:
        opp = self.get(opportunity_id)
        if opp is None:
            raise OpportunityError(f"ärende {opportunity_id} finns inte")
        if opp.stage != stage:
            raise OpportunityError(f"ärende {opportunity_id} väntar på {opp.stage}, inte {stage} (D-011: fast ordning)")
        return opp

    def _acting(self, actor: str):
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise OpportunityError(f"{actor!r} finns inte eller får inte agera just nu")
        return agent

    def _require_role(self, actor: str, role: str) -> None:
        if self._acting(actor).role != role:
            raise OpportunityError(f"bara {role} gör det här steget (D-011)")

    @staticmethod
    def _require_sources(sources: tuple[str, ...]) -> None:
        bad = [s for s in sources if not _SOURCE.fullmatch(s)]
        if not sources or bad:
            raise OpportunityError(f"minst en källa (url: eller file:) krävs, fick {list(sources)}")

    def _log(self, action: str, opportunity_id: int, actor: str, **fields) -> None:
        self._audit.append("research", action, {"opportunity_id": opportunity_id, "actor": actor, **fields})
