"""Authorization Engine (SR-01, SR-02, SR-13, SR-14): får agenten använda verktyget?

Default deny. Svaret är ja bara om **alla** villkor stämmer, i den här ordningen:
1. Verktyget finns i katalogen.
2. Agenten finns i registret.
3. Agenten är i ett tillstånd som får agera (ACTIVE, PROBATION, TESTING).
4. En agent i TESTING får bara agera i sim (SR-13).
5. Inget aktivt stopp från en kontrollfunktion träffar agenten, dess departement eller verktyget (SR-05).
6. Agentens roll har verktyget i sitt mandat.

Styrverktyg (`governance.*`) nekas alltid för agenter (SR-04). Spärrar (`gates=`), som nödstoppet
(SR-07) och det skyddade driftläget (SR-08), kontrolleras före stoppen och mandatet.

Varje beslut, ja eller nej, skrivs till audit-loggen när en sådan finns. Om loggningen
misslyckas blir svaret nej. Systemet ska inte göra något det inte kan bevisa i efterhand (§59).
Samma sak gäller om själva kontrollen misslyckas, till exempel om registret inte kan läsas.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..agents import ACTING_STATES, AgentRegistry, AgentState
from ..audit import AuditLog
from .permissions import PROTECTED_PREFIX, Permissions
from .stops import ControlStops

ENVIRONMENTS = ("sim", "prod")


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    agent_id: str
    tool: str
    reason: str


class PermissionDenied(PermissionError):
    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        super().__init__(f"{decision.agent_id} får inte använda {decision.tool}: {decision.reason}")


class AuthorizationEngine:
    def __init__(
        self,
        permissions: Permissions,
        registry: AgentRegistry,
        environment: str,
        audit: AuditLog | None = None,
        stops: ControlStops | None = None,
        gates: tuple = (),
    ) -> None:
        """`gates`: spärrar med `tool_block_reason(agent, tool) -> str | None`, t.ex. nödstopp (SR-07)."""
        if environment not in ENVIRONMENTS:
            raise ValueError(f"okänd miljö {environment!r}")
        self._permissions = permissions
        self._registry = registry
        self._environment = environment
        self._audit = audit
        self._stops = stops
        self._gates = tuple(gates)

    def check(self, agent_id: str, tool: str) -> Decision:
        try:
            decision = self._decide(agent_id, tool)
        except Exception as exc:  # noqa: BLE001 — t.ex. registret går inte att läsa: kan inte avgöra ⇒ nej
            decision = Decision(False, agent_id, tool, f"kunde inte avgöra ({type(exc).__name__}); nekas")
        if self._audit is None:
            return decision
        try:
            self._audit.append(
                "authorization",
                "tool.allowed" if decision.allowed else "tool.denied",
                {"agent_id": agent_id, "tool": tool, "reason": decision.reason},
            )
        except Exception as exc:  # noqa: BLE001 — vad som än går fel: neka hellre än att agera ologgat
            return Decision(False, agent_id, tool, f"audit-loggen kunde inte skrivas ({type(exc).__name__}); nekas")
        return decision

    def require(self, agent_id: str, tool: str) -> None:
        """Som `check`, men kastar `PermissionDenied` vid nej. Använd före varje verktygsanrop."""
        decision = self.check(agent_id, tool)
        if not decision.allowed:
            raise PermissionDenied(decision)

    def _decide(self, agent_id: str, tool: str) -> Decision:
        def deny(reason: str) -> Decision:
            return Decision(False, agent_id, tool, reason)

        if tool.startswith(PROTECTED_PREFIX):
            return deny("styrverktyg; bara grundarna får ändra konstitution, gränser och mandat (SR-04)")
        if tool not in self._permissions.tools:
            return deny("verktyget finns inte i katalogen")
        agent = self._registry.get(agent_id)
        if agent is None:
            return deny("agenten finns inte i registret")
        if agent.state not in ACTING_STATES:
            return deny(f"agenten är {agent.state.value} och får inte agera")
        if agent.state is AgentState.TESTING and self._environment != "sim":
            return deny("agenten testas och får bara agera i sim (SR-13)")
        for gate in self._gates:  # nödstopp och skyddat driftläge (Fas 4e); ett fel här ger nej via check()
            reason = gate.tool_block_reason(agent, tool)
            if reason:
                return deny(reason)
        if self._stops is not None:
            blocking = self._stops.blocking(agent.agent_id, agent.department, tool)
            if blocking:
                return deny(f"{blocking[0].describe()} (SR-05)")
        mandate = self._permissions.roles.get(agent.role)
        if mandate is None:
            return deny(f"rollen {agent.role!r} saknar mandat")
        if not mandate.allows(tool):
            return deny(f"verktyget ingår inte i mandatet för {agent.role}")
        return Decision(True, agent_id, tool, f"ingår i mandatet för {agent.role}")
