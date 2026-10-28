"""Språkmodellsleverantörer (D-008). Bara gratisalternativ; betalda API:er är spärrade (D-009).

Alla externa leverantörer talar samma OpenAI-kompatibla format (se scripts/llm_smoke_test.py).
Nätverket nås bara via en `Transport`, så testerna kan byta ut den och aldrig gå ut på nätet.
API-nycklar läses från miljövariabler och skrivs aldrig ut eller loggas (SR-10).
"""
from __future__ import annotations

import json
import re
import time
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
    """Anropet misslyckades. Meddelandet innehåller aldrig nyckeln.

    `status` är HTTP-statusen (0 = servern nåddes inte, None = okänt), `code` leverantörens korta
    felkod (t.ex. `rate_limit_exceeded`) och `retry_after` sekunderna i svarshuvudet `Retry-After`.
    """

    def __init__(
        self, message: str, status: int | None = None, code: str = "", retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after


# Utan egen User-Agent skickar urllib "Python-urllib/3.x", som Groqs Cloudflare kan spärra (403).
USER_AGENT = "aie-llm/1.0"
_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,60}")


def _error_code(body: bytes) -> str:
    """Leverantörens felkod (t.ex. `model_not_found`), aldrig fritext som kan eka nyckeln."""
    try:
        error = json.loads(body).get("error") or {}
        code = str(error.get("code") or error.get("type") or "")
    except (ValueError, AttributeError):
        return ""
    return code if _ERROR_CODE.fullmatch(code) else ""


# (url, body, headers, timeout) -> svarets bytes. Kastar ProviderError vid fel.
Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]


def urllib_transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        try:
            code = _error_code(exc.read(4096))
        except OSError:
            code = ""
        try:
            retry_after = float(exc.headers.get("Retry-After", "")) if exc.headers else None
        except ValueError:
            retry_after = None
        # Bara statusen och felkoden; resten av svarskroppen kan eka nyckeln.
        raise ProviderError(
            f"HTTP {exc.code}" + (f" ({code})" if code else ""), exc.code, code, retry_after
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"kunde inte nås: {getattr(exc, 'reason', exc)}", 0) from None


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


RATE_LIMIT_WAIT = 20.0  # sekunder om leverantören inte anger Retry-After
MAX_RATE_LIMIT_WAIT = 60.0


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
        sleep: Callable[[float], None] = time.sleep,
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
        self._sleep = sleep

    def complete(self, request: ChatRequest) -> ChatResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": 0,
        }
        if self.kind == "groq" and self.model.startswith("openai/gpt-oss"):
            # Resonemangstokens räknas mot max_tokens; låg nivå lämnar plats åt själva svaret.
            payload["reasoning_effort"] = "low"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            raw = self._send(body, headers)
        except ProviderError as exc:
            raise ProviderError(
                self._redact(f"{self.name}: {exc}"), exc.status, exc.code, exc.retry_after
            ) from None
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"].get("content") or ""
            tokens = int((data.get("usage") or {}).get("total_tokens") or 0)
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.name}: oväntat svarsformat", 200, "invalid_response") from None
        return ChatResponse(self.name, self.model, text.strip(), tokens)

    def _send(self, body: bytes, headers: Mapping[str, str]) -> bytes:
        """Ett anrop. Vid 429 (gratisgränsen per minut) väntas en gång och anropet görs om (§41)."""
        try:
            return self._transport(self._url, body, headers, self._timeout)
        except ProviderError as exc:
            if exc.status != 429:
                raise
            self._sleep(min(exc.retry_after or RATE_LIMIT_WAIT, MAX_RATE_LIMIT_WAIT))
        return self._transport(self._url, body, headers, self._timeout)

    def __repr__(self) -> str:  # aldrig nyckeln i en repr
        return f"OpenAICompatibleProvider(name={self.name!r}, kind={self.kind!r}, model={self.model!r})"

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***") if self._api_key else text
