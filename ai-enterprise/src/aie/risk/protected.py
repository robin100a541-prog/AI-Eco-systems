"""Skyddat driftläge (Fas 4e-3, SR-08, konstitutionen §59, D-031).

`ProtectedMode.assess()` kontrollerar villkoren i §59. Varje villkor som gäller ger ett skäl:

| §59 | Kontroll i koden |
|---|---|
| Disponibelt kapital närmar sig reservgränsen | disponibelt ≤ 10 % av `MINIMUM_RESERVE`, eller reserven saknas |
| En kritisk behörighetskontroll fungerar inte | `AuthorizationEngine` släpper igenom ett styrverktyg (`governance.change_limits`) |
| Ekonomisk redovisning går inte att verifiera | revisionsloggens hashkedja är bruten, eller ledgerns resultat räknat på två sätt skiljer sig (ER-16) |
| Obehöriga transaktioner | poster i ledgern med `unapproved` som en grundare inte har kvitterat |
| Kritisk säkerhetsincident | en anmäld incident (`report_incident`) |
| En nödvändig kontrollfunktion är otillgänglig | ingen aktiv agent (ACTIVE eller PROBATION) i rollen CFO, CRO, Compliance eller Audit |
| Systemet kan inte avgöra om en handling är tillåten | en kontroll kraschar |

`update()` går in i skyddat läge när minst ett skäl finns. Det sker automatiskt före varje utgift,
eftersom budgetmotorns spärr anropar `update()`. Ett brutet bokföringsunderlag (revisionsloggen,
ledgerns siffror eller obehöriga transaktioner) aktiverar dessutom **nödstoppet** om det är kopplat.

I skyddat läge fortsätter ofarliga uppgifter som analys och dokumentation. **Ekonomiska och externa
handlingar blockeras:** alla utgifter (`BudgetEngine`) och externa verktyg som `research.search`
(`AuthorizationEngine`). Modellanrop tillåts, eftersom ProviderRouter redan håller intern data på
datorn (DR-13).

En grundare lämnar läget med `exit()` först när inget skäl längre gäller. Obehöriga poster kan
kvitteras uttryckligen i samma steg. Händelserna är append-only (migration 17).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..agents import LEVEL_CONTROL, AgentRegistry, AgentState
from ..audit import AuditLog
from ..budget.capital import capital_position
from ..config.models import RiskLimits
from ..ledger import Approval, Ledger, Status, compute_result, recompute
from ..memory import Database

COMPONENT = "system:protected-mode"
RESERVE_MARGIN_PERCENT = 10
CONTROL_ROLES = ("cfo", "cro", "compliance", "auditor")
EXTERNAL_TOOLS = frozenset({"research.search"})
EXTERNAL_PREFIXES = ("external.", "money.", "publish.", "payment.")
_BOOKKEEPING = frozenset({"audit", "ledger", "unauthorized"})  # skäl som också utlöser nödstoppet
_ALIVE = frozenset({AgentState.ACTIVE, AgentState.PROBATION})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ProtectedModeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModeState:
    protected: bool
    since: str | None = None
    reasons: tuple[str, ...] = ()


class ProtectedMode:
    def __init__(
        self,
        db: Database,
        ledger: Ledger,
        registry: AgentRegistry,
        permissions,
        limits: RiskLimits,
        engine,
        audit: AuditLog,
        founders: frozenset[str],
        kill_switch=None,
        clock: Callable[[], str] = _now,
        incidents=None,
    ) -> None:
        """`incidents`: en `IncidentLog`; varje inträde i skyddat läge blir då en incident (FR-15, Fas 5a)."""
        self._db = db
        self._ledger = ledger
        self._registry = registry
        self._permissions = permissions
        self._limits = limits
        self._engine = engine
        self._audit = audit
        self._founders = frozenset(founders)
        self._kill = kill_switch
        self._clock = clock
        self._incident_log = incidents

    # --- Bedömning -----------------------------------------------------------------------

    def assess(self) -> tuple[str, ...]:
        return tuple(text for _, text in self._findings())

    def _findings(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for code, check in (("reserve", self._reserve), ("authorization", self._authorization),
                            ("audit", self._audit_chain), ("ledger", self._ledger_figures),
                            ("unauthorized", self._unauthorized), ("control", self._control_functions),
                            ("incident", self._incidents)):
            try:
                out += [(code, text) for text in check()]
            except Exception as exc:  # noqa: BLE001 — §59: kan systemet inte avgöra räknas det som ett skäl
                out.append(("undecidable", f"kontrollen {code} kunde inte genomföras ({type(exc).__name__}) (§59)"))
        return out

    def _reserve(self) -> list[str]:
        position = capital_position(self._ledger.entries(self._limits.currency), self._limits)
        if position.reserve_minor is None:
            return ["MINIMUM_RESERVE saknas; reserven kan inte skyddas (§59, ER-02)"]
        margin = position.reserve_minor * RESERVE_MARGIN_PERCENT // 100
        if position.disposable_minor <= margin:
            return [f"disponibelt kapital {position.disposable_minor} närmar sig reserven "
                    f"(≤ {RESERVE_MARGIN_PERCENT} % av {position.reserve_minor}) (§59)"]
        return []

    def _authorization(self) -> list[str]:
        agents = list(self._registry.agents())
        if not agents:
            return []
        probe = self._engine.check(agents[0].agent_id, "governance.change_limits")
        if probe.allowed:
            return ["behörighetskontrollen släppte igenom ett styrverktyg (§59, SR-04)"]
        return []

    def _audit_chain(self) -> list[str]:
        check = self._audit.verify()
        if not check.ok:
            return [f"revisionsloggen är bruten vid rad {check.first_bad_seq}: {check.reason} (§59)"]
        return []

    def _ledger_figures(self) -> list[str]:
        currency = self._limits.currency
        reported = compute_result(self._ledger.entries(currency), currency)
        founder = sorted(self._founders)[0]
        diffs = recompute(self._db, self._engine, self._founders, founder, reported)
        if diffs:
            return [f"ledgerns resultat går inte att verifiera: {'; '.join(diffs)} (§59, ER-16)"]
        return []

    def _unauthorized(self) -> list[str]:
        acknowledged = self._acknowledged()
        bad = [e.entry_id for e in self._ledger.entries()
               if e.approval is Approval.UNAPPROVED and e.status in (Status.PENDING, Status.SETTLED)
               and e.entry_id not in acknowledged and not self._ledger.corrections(e.entry_id)]
        if bad:
            return [f"obehöriga transaktioner i ledgern: {bad} (§59)"]
        return []

    def _control_functions(self) -> list[str]:
        alive = {a.role for a in self._registry.agents() if a.state in _ALIVE
                 and self._permissions.roles[a.role].level == LEVEL_CONTROL}
        missing = [r for r in CONTROL_ROLES if r not in alive]
        if missing:
            return [f"kontrollfunktion otillgänglig: {', '.join(missing)} (§59)"]
        return []

    def _incidents(self) -> list[str]:
        return [f"säkerhetsincident: {r}" for r in self._open_incidents()]

    # --- Läge ----------------------------------------------------------------------------

    def state(self) -> ModeState:
        state = ModeState(False)
        for event, reasons, at in self._db.connection.execute(
            "SELECT event, reasons, at FROM operating_mode_events ORDER BY id"
        ):
            if event == "entered" and not state.protected:
                state = ModeState(True, at, tuple(json.loads(reasons)))
            elif event == "exited":
                state = ModeState(False)
        return state

    def update(self) -> ModeState:
        """Går in i skyddat läge om något skäl gäller. Lämnar det aldrig själv; det gör en grundare."""
        findings = self._findings()
        state = self.state()
        if findings and not state.protected:
            reasons = [text for _, text in findings]
            self._event("entered", COMPONENT, reasons)
            self._audit.append(COMPONENT, "mode.protected_entered", {"reasons": reasons, "notify": ["founders"]})
            if self._incident_log is not None:
                self._incident_log.sync()
            state = self.state()
        if self._kill is not None and any(code in _BOOKKEEPING for code, _ in findings):
            self._kill.engage(COMPONENT, "bokföringen går inte att lita på: " +
                              "; ".join(text for code, text in findings if code in _BOOKKEEPING))
        return state

    def report_incident(self, actor: str, description: str) -> ModeState:
        if not description.strip():
            raise ProtectedModeError("beskriv incidenten")
        if actor not in self._founders and actor != COMPONENT:
            agent = self._registry.get(actor)
            if agent is None or agent.state not in _ALIVE or self._permissions.roles[agent.role].level != LEVEL_CONTROL:
                raise ProtectedModeError("bara grundare och kontrollfunktioner anmäler säkerhetsincidenter")
        self._event("incident", actor, [description])
        self._audit.append(actor, "mode.incident", {"description": description})
        return self.update()

    def exit(self, founder: str, reason: str, acknowledge: tuple[int, ...] = ()) -> ModeState:
        """En grundare lämnar skyddat läge. Kräver att inget skäl längre gäller (D-031)."""
        if founder not in self._founders:
            raise ProtectedModeError("bara grundarna kan lämna skyddat driftläge (§59, D-031)")
        if not reason.strip():
            raise ProtectedModeError("ange varför läget kan lämnas")
        if not self.state().protected:
            raise ProtectedModeError("systemet är inte i skyddat driftläge")
        acks = [f"ack:ledger:{i}" for i in acknowledge]
        if acks:  # kvitteringen sparas före bedömningen, så att den räknas
            self._event("incident", founder, [f"kvitterar obehöriga poster {list(acknowledge)}: {reason}", *acks])
        remaining = [text for code, text in self._findings() if code != "incident"]
        if remaining:
            raise ProtectedModeError("skyddat läge kan inte lämnas, skälen gäller fortfarande: " + "; ".join(remaining))
        self._event("exited", founder, [reason])
        self._audit.append(founder, "mode.protected_exited", {"reason": reason, "acknowledged": list(acknowledge)})
        return self.state()

    # --- Spärrar -------------------------------------------------------------------------

    def tool_block_reason(self, agent, tool: str) -> str | None:
        if tool not in EXTERNAL_TOOLS and not tool.startswith(EXTERNAL_PREFIXES):
            return None
        state = self.state()
        if not state.protected:
            return None
        return f"skyddat driftläge sedan {state.since}: externa handlingar blockeras (SR-08)"

    def spend_block_reasons(self, request) -> list[str]:
        state = self.update()  # §59: läget aktiveras automatiskt före varje ekonomisk handling
        if not state.protected:
            return []
        return [f"skyddat driftläge sedan {state.since}: ekonomiska handlingar blockeras (SR-08): "
                + "; ".join(state.reasons)]

    # --- Internt -------------------------------------------------------------------------

    def _events_since_exit(self) -> list[tuple[str, list[str]]]:
        rows = self._db.connection.execute("SELECT event, reasons FROM operating_mode_events ORDER BY id").fetchall()
        out: list[tuple[str, list[str]]] = []
        for event, reasons in rows:
            if event == "exited":
                out = []
            else:
                out.append((event, json.loads(reasons)))
        return out

    def _open_incidents(self) -> list[str]:
        return [reasons[0] for event, reasons in self._events_since_exit()
                if event == "incident" and not any(r.startswith("ack:") for r in reasons)]

    def _acknowledged(self) -> set[int]:
        acks: set[int] = set()
        for (reasons,) in self._db.connection.execute(
            "SELECT reasons FROM operating_mode_events WHERE event = 'incident'"
        ):
            acks |= {int(r.split(":")[-1]) for r in json.loads(reasons) if r.startswith("ack:ledger:")}
        return acks

    def _event(self, event: str, actor: str, reasons: list[str]) -> None:
        with self._db.transaction() as tx:
            tx.execute("INSERT INTO operating_mode_events (event, actor, reasons, at) VALUES (?, ?, ?, ?)",
                       (event, actor, json.dumps(reasons, ensure_ascii=False), self._clock()))
