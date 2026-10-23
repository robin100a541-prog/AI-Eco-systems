"""LLMGateway: det enda sättet för en agent att nå ProviderRouter (SR-01, SR-02, §35–36).

Agenter får aldrig en `ProviderRouter` direkt, bara en `LLMGateway`. Varje anrop går så här:
1. **Behörighet:** Authorization Engine måste tillåta verktyget `llm.complete` för agenten.
   Ett nej loggas i audit-loggen av motorn, och inget skickas (default deny).
2. **Hemligheter:** en prompt som innehåller något som ser ut som en hemlighet (en nyckel
   som `api_key=...`, eller värdet av en hemlig miljövariabel) avvisas helt, oavsett
   dataklass. Nycklar hör aldrig hemma i en prompt (SR-10). Avvisningen loggas utan prompten.
3. **Routern:** först därefter går förfrågan till `ProviderRouter`, som själv ser till att
   bara `public` lämnar datorn (DR-13) och att kvoterna räknas (DR-12).
"""

from __future__ import annotations

from ..audit import AuditLog
from ..authorization import AuthorizationEngine
from ..monitoring import get_logger, mask_secrets
from .providers import ChatRequest, ChatResponse
from .router import ProviderRouter

TOOL = "llm.complete"

log = get_logger("llm")


class SecretInPrompt(ValueError):
    """Prompten innehåller en hemlighet och skickas inte någonstans."""


class LLMGateway:
    def __init__(
        self, router: ProviderRouter, engine: AuthorizationEngine, audit: AuditLog
    ) -> None:
        self._router = router
        self._engine = engine
        self._audit = audit

    def complete(self, agent_id: str, request: ChatRequest) -> ChatResponse:
        """Kastar `PermissionDenied`, `SecretInPrompt` eller `NoProviderAvailable` vid nej."""
        self._engine.require(agent_id, TOOL)
        if any(mask_secrets(m.content) != m.content for m in request.messages):
            self._audit.append(
                "llm",
                "llm.blocked_secret",
                {"caller": agent_id, "data_class": request.data_class.value},
            )
            log.warning("prompt från %s avvisad: innehåller en hemlighet", agent_id)
            raise SecretInPrompt(
                "prompten innehåller en hemlighet och skickas inte (SR-10)"
            )
        return self._router.complete(request, caller=agent_id)
