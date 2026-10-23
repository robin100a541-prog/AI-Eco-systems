"""Språkmodellsleverantörer (D-008). Bara gratisalternativ; betalda API:er är spärrade (D-009).

Alla externa leverantörer talar samma OpenAI-kompatibla format (se scripts/llm_smoke_test.py).
Nätverket nås bara via en `Transport`, så testerna kan byta ut den och aldrig gå ut på nätet.
API-nycklar läses från miljövariabler och skrivs aldrig ut eller loggas (SR-10).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum


class DataClass(str, Enum):
    """Dataklassning (DR-13). Bara `public` får lämna datorn."""

    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SECRET = "secret"


ALL_CLASSES = frozenset(DataClass)
PUBLIC_ONLY = frozenset({DataClass.PUBLIC})


@dataclass(frozen=True, slots=True)
class Message:
    role: str  # "system", "user" eller "assistant"
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: tuple[Message, ...]
    data_class: DataClass
    max_tokens: int = 512


@dataclass(frozen=True, slots=True)
class ChatResponse:
    provider: str
    model: str
    text: str
    tokens: int  # totalt enligt leverantören; 0 om okänt


class ProviderError(RuntimeError):
    """Anropet misslyckades. Meddelandet innehåller aldrig nyckeln."""


# (url, body, headers, timeout) -> svarets bytes. Kastar ProviderError vid fel.
Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]


def urllib_transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"HTTP {exc.code}") from None  # svarskroppen kan eka nyckeln
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"kunde inte nås: {getattr(exc, 'reason', exc)}") from None


class Provider:
    """Gemensamt gränssnitt. `allowed_classes` styr vilka data som får skickas hit (DR-13)."""

    name: str
    model: str
    allowed_classes: frozenset[DataClass]
    external: bool

    def complete(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover — abstrakt
        raise NotImplementedError


class RuleProvider(Provider):
    """Deterministisk "modell" i ren Python. Används i tester och simulering och är alltid tillgänglig."""

    external = False

    def __init__(self, name: str = "rule", responder: Callable[[ChatRequest], str] | None = None) -> None:
        self.name = name
        self.model = "rule"
        self.allowed_classes = ALL_CLASSES
        self._responder = responder or (lambda req: f"[rule] {req.messages[-1].content}")

    def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(self.name, self.model, self._responder(request), tokens=0)


KINDS = {
    # kind: (bas-URL, miljövariabel för nyckel, extern)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", True),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", True),
    "ollama": ("http://localhost:11434/v1", None, False),
}


class OpenAICompatibleProvider(Provider):
    def __init__(
        self,
        name: str,
        kind: str,
        model: str,
        api_key: str | None,
        transport: Transport = urllib_transport,
        base_url: str | None = None,
        timeout: float = 60,
    ) -> None:
        if kind not in KINDS:
            raise ValueError(f"okänd leverantörstyp {kind!r}")
        if kind == "openrouter" and not model.endswith(":free"):
            raise ValueError("OpenRouter-modellen måste sluta på ':free'; annars kan anropet kosta pengar (§42)")
        default_url, key_env, external = KINDS[kind]
        if key_env and not api_key:
            raise ValueError(f"{key_env} saknas")
        self.name, self.kind, self.model = name, kind, model
        self.external = external
        self.allowed_classes = PUBLIC_ONLY if external else ALL_CLASSES
        self._api_key = api_key
        self._transport = transport
        self._url = f"{base_url or default_url}/chat/completions"
        self._timeout = timeout

    def complete(self, request: ChatRequest) -> ChatResponse:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": 0,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            raw = self._transport(self._url, body, headers, self._timeout)
        except ProviderError as exc:
            raise ProviderError(self._redact(f"{self.name}: {exc}")) from None
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"].get("content") or ""
            tokens = int((data.get("usage") or {}).get("total_tokens") or 0)
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.name}: oväntat svarsformat") from None
        return ChatResponse(self.name, self.model, text.strip(), tokens)

    def __repr__(self) -> str:  # aldrig nyckeln i en repr
        return f"OpenAICompatibleProvider(name={self.name!r}, kind={self.kind!r}, model={self.model!r})"

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***") if self._api_key else text
