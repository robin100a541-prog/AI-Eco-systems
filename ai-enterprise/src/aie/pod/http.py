"""JSON över HTTPS med standardbiblioteket (arbetsorder 04, D-065).

`JsonClient` används av alla externa klienter i `aie.pod`:
- **Bara https** och bara mot klientens egen bas-URL. En URL utanför den avvisas innan något skickas.
- **Egen User-Agent** (`USER_AGENT`) på varje anrop. Printify kräver det.
- **Tidsgräns** per anrop (`timeout`).
- **Rate limits:** ett minsta avstånd mellan anrop (`min_interval`). Vid HTTP 429 och 5xx görs högst
  `retries` nya försök. Väntetiden följer `Retry-After` om svaret har en, annars dubblas den, med tak
  `max_wait`. Är det fortfarande 429 efter sista försöket kastas `RateLimited`.
- **Hemligheter:** rubrikerna med nyckeln byggs av klienten och finns aldrig i felmeddelanden, loggar
  eller `repr`. Ett fel anger metod, sökväg och status, aldrig rubriker eller frågesträng.

Transporten kan bytas ut. Testerna gör aldrig några nätverksanrop.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

USER_AGENT = "ai-eco-systems/aie (+https://github.com/robin100a541-prog/AI-Eco-systems)"


class ApiError(RuntimeError):
    """Ett anrop misslyckades. Texten innehåller aldrig nyckeln."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RateLimited(ApiError):
    """HTTP 429 även efter alla återförsök."""


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


# (metod, url, rubriker, kropp, timeout) -> Response; kastar ApiError(status=None) vid nätverksfel
Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], Response]


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                     timeout: float) -> Response:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:  # noqa: S310 — https kontrolleras före
            return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read() or b"")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(f"nätverksfel: {type(exc).__name__}") from None


class JsonClient:
    def __init__(self, base_url: str, auth_headers: Mapping[str, str], *, transport: Transport = urllib_transport,
                 timeout: float = 30.0, retries: int = 3, min_interval: float = 0.2, max_wait: float = 60.0,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("bara https")
        self._base = base_url.rstrip("/")
        self._host = urlsplit(self._base).hostname
        self._auth = dict(auth_headers)
        self._transport = transport
        self._timeout = timeout
        self._retries = retries
        self._min_interval = min_interval
        self._max_wait = max_wait
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self.calls = 0  # antal HTTP-anrop, även återförsök

    def __repr__(self) -> str:  # aldrig nyckeln
        return f"JsonClient({self._base!r})"

    def get(self, path: str, params: Mapping[str, object] | None = None):
        return self.request("GET", path, params=params)

    def post(self, path: str, payload: object):
        return self.request("POST", path, payload=payload)

    def put(self, path: str, payload: object):
        return self.request("PUT", path, payload=payload)

    def request(self, method: str, path: str, *, params: Mapping[str, object] | None = None, payload: object = None):
        if not path.startswith("/") or "//" in path or ".." in path:
            raise ValueError(f"ogiltig sökväg {path!r}")
        url = self._base + path + (f"?{urlencode(params, doseq=True)}" if params else "")
        if urlsplit(url).hostname != self._host:
            raise ValueError("anropet lämnar klientens värd")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **self._auth}
        if body is not None:
            headers["Content-Type"] = "application/json"
        wait = 1.0
        for attempt in range(self._retries + 1):
            self._pace()
            self.calls += 1
            try:
                response = self._transport(method, url, headers, body, self._timeout)
            except ApiError as exc:
                if attempt == self._retries:
                    raise ApiError(f"{method} {path}: {exc}") from None
                self._sleep(min(wait, self._max_wait))
                wait *= 2
                continue
            if response.status == 429 or response.status >= 500:
                if attempt == self._retries:
                    cls = RateLimited if response.status == 429 else ApiError
                    raise cls(f"{method} {path}: HTTP {response.status} efter {attempt + 1} försök", response.status)
                self._sleep(min(_retry_after(response.headers, wait), self._max_wait))
                wait *= 2
                continue
            if response.status >= 400:
                raise ApiError(f"{method} {path}: HTTP {response.status}: {self._redact(_short(response.body))}",
                               response.status)
            if not response.body:
                return None
            try:
                return json.loads(response.body)
            except ValueError:
                raise ApiError(f"{method} {path}: svaret är inte JSON", response.status) from None
        raise AssertionError("nås inte")

    def _redact(self, text: str) -> str:
        for value in self._auth.values():
            for secret in {value, value.split(" ", 1)[-1]}:
                if len(secret) >= 8:
                    text = text.replace(secret, "***")
        return text

    def _pace(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._min_interval:
            self._sleep(self._min_interval - (now - self._last))
        self._last = self._clock()


def _retry_after(headers: Mapping[str, str], default: float) -> float:
    value = {k.lower(): v for k, v in headers.items()}.get("retry-after")
    try:
        return max(0.0, float(value)) if value is not None else default
    except ValueError:
        return default


def _short(body: bytes) -> str:
    text = body[:300].decode("utf-8", "replace").replace("\n", " ")
    return text if len(body) <= 300 else text + "…"
