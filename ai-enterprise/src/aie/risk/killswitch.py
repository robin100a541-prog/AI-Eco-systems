"""Nödstopp / kill switch (Fas 4e-2, SR-07, konstitutionen §38, D-030).

När nödstoppet är aktivt gäller:
- **Inga nya ekonomiska transaktioner.** `BudgetEngine` blockerar varje utgift (spärr via `gates=`).
- **Automatiserade externa handlingar pausas,** och **verktygsbehörigheterna begränsas.**
  `AuthorizationEngine` nekar alla verktyg utom de som behövs för att förstå läget och
  dokumentera det: läsa och skriva rapporter, läsa ledgern, verifiera revisionsloggen,
  riskbedöma och stoppa. Det innebär bland annat inga språkmodellsanrop, ingen webbsökning
  och inga nya eller tilldelade uppgifter.
- **Inget raderas** (§38). Ledgern tar fortfarande emot fakta (D-024), och alla register och
  loggar bevaras. Nödstoppet ändrar inga befintliga data.
- **Människor informeras:** varje aktivering och återstart loggas i revisionsloggen med vilka
  som ska informeras.

Vem kan aktivera: grundarna, aktiva kontrollfunktioner (nivå 2 med `action.block`) och de
systemkomponenter som uttryckligen anges, till exempel `system:protected-mode`.

**Återstart enligt dokumenterad process** (`docs/operations.md`, D-030): två *olika* grundare
röstar var för sig med `release_vote` efter den senaste aktiveringen, och revisionsloggens
hashkedja måste vara intakt vid varje röst. Först efter den andra rösten släpps nödstoppet.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..agents import ACTING_STATES, LEVEL_CONTROL, AgentRegistry
from ..audit import AuditLog
from ..memory import Database

SAFE_TOOLS = frozenset({"report.read", "report.write", "ledger.read", "audit.verify", "risk.assess", "action.block"})
BLOCK_TOOL = "action.block"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class KillSwitchError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class KillState:
    engaged: bool
    engaged_by: str | None = None
    reason: str | None = None
    engaged_at: str | None = None
    release_votes: tuple[str, ...] = ()  # grundare som har röstat för återstart sedan aktiveringen


class KillSwitch:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions,
        audit: AuditLog,
        founders: frozenset[str],
        components: frozenset[str] = frozenset(),
        clock: Callable[[], str] = _now,
        incidents=None,
    ) -> None:
        """`incidents`: en `IncidentLog`; varje aktivering blir då en incident (FR-15, Fas 5a)."""
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._components = frozenset(components)
        self._clock = clock
        self._incident_log = incidents

    # --- Kommandon -------------------------------------------------------------------------

    def engage(self, actor: str, reason: str) -> KillState:
        if not reason.strip():
            raise KillSwitchError("ange varför nödstoppet aktiveras")
        self._require_engager(actor)
        state = self.state()
        if state.engaged:
            return state  # redan aktivt; ingen ny händelse behövs
        self._event("engaged", actor, reason)
        self._audit.append(actor, "kill.engaged", {"reason": reason, "notify": ["founders", "role:cro", "role:auditor"]})
        if self._incident_log is not None:
            self._incident_log.sync()
        return self.state()

    def vote_release(self, founder: str, reason: str) -> KillState:
        """En grundares röst för återstart. Två olika grundare krävs (D-030)."""
        if founder not in self._founders:
            raise KillSwitchError("bara grundarna kan starta om efter ett nödstopp (§38, D-030)")
        if not reason.strip():
            raise KillSwitchError("ange varför systemet kan startas om")
        state = self.state()
        if not state.engaged:
            raise KillSwitchError("nödstoppet är inte aktivt")
        if founder in state.release_votes:
            raise KillSwitchError(f"{founder} har redan röstat; den andra grundaren måste också rösta")
        check = self._audit.verify()
        if not check.ok:
            raise KillSwitchError(
                f"revisionsloggen är trasig vid rad {check.first_bad_seq} ({check.reason}); "
                "ingen återstart förrän det är utrett (§38, §59)"
            )
        self._event("release_vote", founder, reason)
        votes = (*state.release_votes, founder)
        if len(set(votes)) >= 2:
            self._event("released", founder, f"återstart godkänd av {', '.join(votes)}")
            self._audit.append(founder, "kill.released", {"votes": list(votes), "reason": reason})
        else:
            self._audit.append(founder, "kill.release_vote", {"votes": list(votes), "reason": reason})
        return self.state()

    # --- Läge ------------------------------------------------------------------------------

    def state(self) -> KillState:
        rows = self._db.connection.execute(
            "SELECT event, actor, reason, at FROM kill_switch_events ORDER BY id"
        ).fetchall()
        state = KillState(False)
        for event, actor, reason, at in rows:
            if event == "engaged":
                state = KillState(True, actor, reason, at)
            elif event == "release_vote" and state.engaged:
                state = KillState(True, state.engaged_by, state.reason, state.engaged_at,
                                  (*state.release_votes, actor))
            elif event == "released":
                state = KillState(False)
        return state

    # --- Spärrar ---------------------------------------------------------------------------

    def tool_block_reason(self, agent, tool: str) -> str | None:
        """För AuthorizationEngine. None = nödstoppet hindrar inte verktyget."""
        if tool in SAFE_TOOLS:
            return None
        state = self.state()
        if not state.engaged:
            return None
        return f"nödstopp aktivt sedan {state.engaged_at} av {state.engaged_by}: {state.reason} (SR-07)"

    def spend_block_reasons(self, request) -> list[str]:
        """För BudgetEngine: inga nya ekonomiska transaktioner under nödstopp."""
        state = self.state()
        if not state.engaged:
            return []
        return [f"nödstopp aktivt sedan {state.engaged_at}: inga nya ekonomiska transaktioner (SR-07)"]

    # --- Internt ---------------------------------------------------------------------------

    def _require_engager(self, actor: str) -> None:
        if actor in self._founders or actor in self._components:
            return
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise KillSwitchError(f"{actor!r} finns inte eller får inte agera just nu")
        mandate = self._permissions.roles[agent.role]
        if mandate.level != LEVEL_CONTROL or BLOCK_TOOL not in mandate.tools:
            raise KillSwitchError("bara grundare, kontrollfunktioner och angivna systemkomponenter aktiverar nödstoppet")

    def _event(self, event: str, actor: str, reason: str) -> None:
        with self._db.transaction() as tx:
            tx.execute("INSERT INTO kill_switch_events (event, actor, reason, at) VALUES (?, ?, ?, ?)",
                       (event, actor, reason, self._clock()))
