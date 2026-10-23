"""Kontrollfunktionernas stopp (SR-05, konstitutionen §8 nivå 2).

> Dessa roller ska kunna stoppa åtgärder inom sina uttryckligen tilldelade kontrollområden.
> Ingen operativ chef får ensam åsidosätta ett obligatoriskt säkerhetsstopp.

Regler som koden upprätthåller:
- **Sätta ett stopp:** en grundare, eller en kontrollfunktion (nivå 2) som är aktiv och har
  `action.block` i sitt mandat. Ett stopp gäller en agent, ett departement eller ett verktyg.
- **Kontrollfunktionerna stoppar inte varandra.** Ett stopp mot en agent på nivå 2, eller mot
  departementen finance, risk, compliance och audit, får bara grundarna sätta. Annars kunde
  den som granskas stänga av sin granskare (§18).
- **Häva ett stopp:** bara den som satte det, eller en grundare. Ingen operativ agent, inte
  ens CEO, kan häva det, och inte heller en annan kontrollfunktion.
- Stopp raderas aldrig. Att häva ett stopp kräver en motivering och sparas (migration 7).
- Varje satt och hävt stopp skrivs till audit-loggen.

`AuthorizationEngine(..., stops=ControlStops(...))` nekar alla verktyg för en agent som omfattas
av ett aktivt stopp: agenten själv, agentens departement eller själva verktyget.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..agents import ACTING_STATES, LEVEL_CONTROL, AgentRegistry
from ..audit import AuditLog
from ..memory import Database

if TYPE_CHECKING:
    from .permissions import Permissions

SCOPES = ("agent", "department", "tool")
CONTROL_DEPARTMENTS = frozenset({"finance", "risk", "compliance", "audit"})
BLOCK_TOOL = "action.block"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StopError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Stop:
    stop_id: int
    scope_kind: str
    scope_value: str
    reason: str
    placed_by: str
    placed_at: str
    lifted_by: str | None = None
    lifted_at: str | None = None
    lift_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.lifted_at is None

    def describe(self) -> str:
        return f"stopp #{self.stop_id} ({self.scope_kind} {self.scope_value}) av {self.placed_by}: {self.reason}"


class ControlStops:
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

    # --- Kommandon -------------------------------------------------------------------------

    def place(self, actor: str, scope_kind: str, scope_value: str, reason: str) -> Stop:
        if scope_kind not in SCOPES:
            raise StopError(f"okänd omfattning {scope_kind!r} (tillåtna: {', '.join(SCOPES)})")
        if not reason.strip():
            raise StopError("ett stopp kräver en motivering")
        self._check_target(scope_kind, scope_value)
        if actor not in self._founders:
            self._require_control_function(actor)
            if self._protects_control(scope_kind, scope_value):
                raise StopError("kontrollfunktioner stoppar inte varandra; bara grundarna kan stoppa dem (§18)")
            if scope_kind == "agent" and scope_value == actor:
                raise StopError("en agent kan inte stoppa sig själv")
        now = self._clock()
        with self._db.transaction() as tx:
            cursor = tx.execute(
                "INSERT INTO control_stops (scope_kind, scope_value, reason, placed_by, placed_at) VALUES (?, ?, ?, ?, ?)",
                (scope_kind, scope_value, reason, actor, now),
            )
            stop = Stop(cursor.lastrowid, scope_kind, scope_value, reason, actor, now)
        self._audit.append("control", "stop.placed", {
            "stop_id": stop.stop_id, "scope_kind": scope_kind, "scope_value": scope_value,
            "reason": reason, "placed_by": actor,
        })
        return stop

    def lift(self, actor: str, stop_id: int, reason: str) -> Stop:
        if not reason.strip():
            raise StopError("att häva ett stopp kräver en motivering")
        stop = self.get(stop_id)
        if stop is None:
            raise StopError(f"stopp #{stop_id} finns inte")
        if not stop.active:
            raise StopError(f"stopp #{stop_id} är redan hävt")
        if actor not in self._founders and actor != stop.placed_by:
            raise StopError(
                f"bara {stop.placed_by} eller en grundare kan häva stopp #{stop_id}; "
                "ingen operativ chef kan häva ett obligatoriskt stopp (SR-05)"
            )
        now = self._clock()
        with self._db.transaction() as tx:
            tx.execute(
                "UPDATE control_stops SET lifted_by = ?, lifted_at = ?, lift_reason = ? WHERE stop_id = ?",
                (actor, now, reason, stop_id),
            )
        self._audit.append("control", "stop.lifted", {"stop_id": stop_id, "lifted_by": actor, "reason": reason})
        return Stop(**{**_fields(stop), "lifted_by": actor, "lifted_at": now, "lift_reason": reason})

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, stop_id: int) -> Stop | None:
        row = self._db.connection.execute(_SELECT + " WHERE stop_id = ?", (stop_id,)).fetchone()
        return None if row is None else Stop(*row)

    def active(self) -> tuple[Stop, ...]:
        rows = self._db.connection.execute(_SELECT + " WHERE lifted_at IS NULL ORDER BY stop_id")
        return tuple(Stop(*r) for r in rows)

    def blocking(self, agent_id: str, department: str, tool: str) -> tuple[Stop, ...]:
        """Aktiva stopp som träffar just den här agenten, dess departement eller verktyget."""
        targets = {("agent", agent_id), ("department", department), ("tool", tool)}
        return tuple(s for s in self.active() if (s.scope_kind, s.scope_value) in targets)

    # --- Internt ---------------------------------------------------------------------------

    def _require_control_function(self, actor: str) -> None:
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise StopError(f"{actor!r} finns inte eller får inte agera just nu")
        mandate = self._permissions.roles[agent.role]
        if mandate.level != LEVEL_CONTROL or BLOCK_TOOL not in mandate.tools:
            raise StopError(f"{actor!r} är ingen kontrollfunktion med {BLOCK_TOOL} (§8 nivå 2)")

    def _protects_control(self, scope_kind: str, scope_value: str) -> bool:
        if scope_kind == "department":
            return scope_value in CONTROL_DEPARTMENTS
        if scope_kind == "agent":
            agent = self._registry.get(scope_value)
            return agent is not None and self._permissions.roles[agent.role].level == LEVEL_CONTROL
        return scope_value == BLOCK_TOOL  # att stoppa själva stoppverktyget vore att stoppa alla kontrollfunktioner

    def _check_target(self, scope_kind: str, scope_value: str) -> None:
        if scope_kind == "agent" and self._registry.get(scope_value) is None:
            raise StopError(f"agenten {scope_value!r} finns inte")
        if scope_kind == "department" and scope_value not in {m.department for m in self._permissions.roles.values()}:
            raise StopError(f"departementet {scope_value!r} finns inte i permissions.toml")
        if scope_kind == "tool" and scope_value not in self._permissions.tools:
            raise StopError(f"verktyget {scope_value!r} finns inte i katalogen")


_SELECT = (
    "SELECT stop_id, scope_kind, scope_value, reason, placed_by, placed_at, lifted_by, lifted_at, lift_reason "
    "FROM control_stops"
)


def _fields(stop: Stop) -> dict:
    return {name: getattr(stop, name) for name in Stop.__slots__}
