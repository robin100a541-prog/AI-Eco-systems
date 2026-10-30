"""Webbläsning för Research (PR 5, D-057, SR-06, DR-13).

`WebReader.fetch(agent, url)` läser en offentlig webbsida med standardbiblioteket. I tur och ordning:

1. **Behörighet:** `AuthorizationEngine.require(agent, "research.search")`. Verktyget blockeras därmed
   av nödstoppet (SR-07) och i skyddat driftläge (SR-08), och bara roller med verktyget kan använda det.
2. **URL:** bara `http`/`https`, inga inloggningsuppgifter i adressen, bara standardportar och bara
   värdar i `allowed_hosts` i `config/research.toml`. Tills ett gratis sök-API är utrett (R-11) hämtas
   bara kända sidor.
3. **SSRF-skydd:** värdnamnet slås upp, och varje adress måste vara offentlig. Privata, lokala,
   länklokala, reserverade adresser och multicast stoppas, både i början och efter varje omdirigering.
4. **Kvot:** högst `per_day` försök per dag för alla agenter tillsammans, reserverat atomärt före DNS/HTTP.
   Fel, avvisade adresser och avbrott räknas också. Ett försök kan omfatta robots.txt och begränsade omdirigeringar.
5. **robots.txt:** sidan hämtas bara om webbplatsens `robots.txt` tillåter det för vår user-agent.
   Saknas filen tillåts hämtningen, enligt standarden.
6. **Hämtning:** bara GET, aldrig formulär eller POST. Tidsgräns `timeout_seconds`, högst `max_bytes`
   (resten kortas av och märks), högst `max_redirects` omdirigeringar, och bara text, HTML, JSON eller XML.
7. **Lagring:** varje försök sparas med URL, datum, utfall och SHA-256, och innehållet som text
   (migration 30, append-only). Innehållet returneras som `ExternalContent`: opålitlig data som ramas in
   och aldrig ger behörighet (SR-06). Försök att styra agenten (`injection_signals`) loggas.

Begränsning: värdnamnet kontrolleras före anslutningen. En DNS-ändring mellan kontrollen och
anslutningen kan inte uteslutas helt, och därför tillåts bara kända värdar.
"""
from __future__ import annotations

import hashlib
import ipaddress
import socket
import tomllib
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..audit import AuditLog
from ..config import ConfigError
from ..memory import Database
from ..security import ExternalContent

TOOL = "research.search"
RESEARCH_FILE = "research.toml"
TEXT_TYPES = ("text/html", "text/plain", "application/json", "application/xml", "text/xml", "application/xhtml+xml")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class WebError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WebLimits:
    per_day: int
    max_bytes: int
    timeout_seconds: int
    max_redirects: int
    user_agent: str
    allowed_hosts: frozenset[str]


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    truncated: bool


@dataclass(frozen=True, slots=True)
class WebPage:
    fetch_id: int
    url: str
    final_url: str
    content: ExternalContent
    truncated: bool
    signals: tuple[str, ...]


def load_limits(config_dir: Path | str) -> WebLimits:
    path = Path(config_dir) / RESEARCH_FILE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{RESEARCH_FILE}: filen saknas i {config_dir}"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError([f"{RESEARCH_FILE}: kan inte tolkas som TOML: {exc}"]) from None
    errors = []
    for key in ("per_day", "max_bytes", "timeout_seconds", "max_redirects"):
        v = data.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v < (0 if key == "max_redirects" else 1):
            errors.append(f"{RESEARCH_FILE}: {key} ska vara ett positivt heltal")
    hosts = data.get("allowed_hosts")
    if not isinstance(hosts, list) or not all(isinstance(h, str) and h == h.lower() and h.strip() for h in hosts):
        errors.append(f"{RESEARCH_FILE}: allowed_hosts ska vara en lista med värdnamn i gemener")
    if not isinstance(data.get("user_agent"), str) or not data["user_agent"].strip():
        errors.append(f"{RESEARCH_FILE}: user_agent saknas")
    if errors:
        raise ConfigError(errors)
    return WebLimits(data["per_day"], data["max_bytes"], data["timeout_seconds"], data["max_redirects"],
                     data["user_agent"], frozenset(hosts))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 — omdirigeringar prövas en i taget
        return None


def urllib_get(url: str, headers: dict[str, str], timeout: int, max_bytes: int) -> Response:
    """En GET utan automatiska omdirigeringar. `WebReader` prövar varje omdirigering själv."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, body[:max_bytes],
                            len(body) > max_bytes)
    except urllib.error.HTTPError as exc:  # 3xx utan följning, 4xx och 5xx
        return Response(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, b"", False)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WebError(f"kunde inte nås: {getattr(exc, 'reason', exc)}") from None


def resolve_ips(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except socket.gaierror as exc:
        raise WebError(f"värden {host!r} kunde inte slås upp: {exc}") from None


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    return "\n".join(parser.parts)


class WebReader:
    def __init__(self, db: Database, engine, audit: AuditLog, limits: WebLimits,
                 get: Callable[..., Response] = urllib_get, resolve: Callable[[str], list[str]] = resolve_ips,
                 clock: Callable[[], str] = _now) -> None:
        """`get` och `resolve` byts mot attrapper i testerna, så att inga nätverksanrop görs."""
        self._db = db
        self._engine = engine
        self._audit = audit
        self._limits = limits
        self._get = get
        self._resolve = resolve
        self._clock = clock
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def fetch(self, agent: str, url: str, secret_headers: dict[str, str] | None = None) -> WebPage:
        """`secret_headers` (t.ex. en API-nyckel) skickas bara till adressens egen värd och sparas aldrig."""
        self._engine.require(agent, TOOL)  # PermissionDenied vid nej; nödstopp och skyddat läge ingår
        try:
            self._reserve_attempt()
            self._check_url(url)
            if not self._robots_allow(url):
                raise WebError("robots.txt tillåter inte hämtningen")
            final_url, response = self._follow(url, secret_headers)
        except WebError as exc:
            self._store(agent, url, None, "refused", None, None, b"", "", False, str(exc))
            raise
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if response.status != 200:
            reason = f"svarade {response.status}"
            self._store(agent, url, final_url, "error", response.status, content_type, b"", "", False, reason)
            raise WebError(reason)
        if content_type not in TEXT_TYPES:
            reason = f"innehållstypen {content_type or 'okänd'} hämtas inte, bara text"
            self._store(agent, url, final_url, "refused", response.status, content_type, b"", "", False, reason)
            raise WebError(reason)
        raw = response.body.decode(_charset(response.headers.get("content-type", "")), errors="replace")
        text = html_to_text(raw) if "html" in content_type else raw
        fetch_id = self._store(agent, url, final_url, "ok", response.status, content_type, response.body, text,
                               response.truncated, "hämtad")
        content = ExternalContent(f"url:{final_url}", text)
        signals = content.signals()
        if signals:  # loggas utan innehållet (SR-06, SR-10)
            self._audit.append(f"agent:{agent}", "external.injection_suspected",
                               {"fetch_id": fetch_id, "source": f"url:{final_url}", "signals": list(signals)})
        return WebPage(fetch_id, url, final_url, content, response.truncated, signals)

    def _reserve_attempt(self) -> None:
        """Reserve before DNS/HTTP; failures and interrupted requests still count."""
        day = self._clock()[:10]
        with self._db.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO web_attempt_usage (day, attempts) VALUES (?, 0)", (day,))
            changed = tx.execute("UPDATE web_attempt_usage SET attempts = attempts + 1 "
                                 "WHERE day = ? AND attempts < ?", (day, self._limits.per_day)).rowcount
            if changed != 1:
                raise WebError(f"dagens kvot på {self._limits.per_day} hämtningar är slut")

    def used_today(self) -> int:
        row = self._db.connection.execute(
            "SELECT attempts FROM web_attempt_usage WHERE day = ?", (self._clock()[:10],)).fetchone()
        return row[0] if row else 0

    def history(self, limit: int = 50) -> list[dict]:
        rows = self._db.connection.execute(
            "SELECT id, agent, url, outcome, status_code, bytes, reason, at FROM web_fetches ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        keys = ("id", "agent", "url", "outcome", "status_code", "bytes", "reason", "at")
        return [dict(zip(keys, r)) for r in rows]

    # --- Internt ---------------------------------------------------------------------------

    def _check_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise WebError("bara http och https")
        if parts.username or parts.password:
            raise WebError("inloggningsuppgifter i adressen är inte tillåtna")
        if parts.port not in (None, 80, 443):
            raise WebError("bara standardportar (80 och 443)")
        host = (parts.hostname or "").lower()
        if host not in self._limits.allowed_hosts:
            raise WebError(f"värden {host!r} finns inte i allowed_hosts (config/research.toml); bara kända sidor (R-11)")
        ips = self._resolve(host)
        if not ips:
            raise WebError(f"värden {host!r} har ingen adress")
        for ip in ips:
            address = ipaddress.ip_address(ip)
            if not address.is_global or address.is_multicast:
                raise WebError(f"värden {host!r} pekar på en icke-offentlig adress ({ip}); stoppas (SSRF)")

    def _robots_allow(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            response = self._get(f"{base}/robots.txt", self._headers(), self._limits.timeout_seconds, 200_000)
            if response.status == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(response.body.decode("utf-8", errors="replace").splitlines())
                self._robots[base] = parser
            elif response.status in (401, 403):
                self._robots[base] = _deny_all()
            else:
                self._robots[base] = None  # ingen robots.txt: tillåtet enligt standarden
        parser = self._robots[base]
        return parser is None or parser.can_fetch(self._limits.user_agent, url)

    def _follow(self, url: str, secret_headers: dict[str, str] | None = None) -> tuple[str, Response]:
        current = url
        host = urlsplit(url).hostname
        for _ in range(self._limits.max_redirects + 1):
            headers = self._headers()
            if secret_headers and urlsplit(current).hostname == host:  # nyckeln följer aldrig till en annan värd
                headers |= secret_headers
            response = self._get(current, headers, self._limits.timeout_seconds, self._limits.max_bytes)
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise WebError("omdirigering utan adress")
                current = urljoin(current, location)
                self._check_url(current)  # varje nytt mål prövas på nytt (SSRF, kända värdar)
                if not self._robots_allow(current):
                    raise WebError("robots.txt tillåter inte omdirigeringens mål")
                continue
            return current, response
        raise WebError(f"fler än {self._limits.max_redirects} omdirigeringar")

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._limits.user_agent, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1"}

    def _store(self, agent, url, final_url, outcome, status, content_type, body: bytes, text: str, truncated,
               reason) -> int:
        now = self._clock()
        with self._db.transaction() as tx:
            fetch_id = tx.execute(
                "INSERT INTO web_fetches (agent, url, final_url, outcome, status_code, content_type, bytes, sha256, "
                "text, truncated, reason, day, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent, url, final_url, outcome, status, content_type, len(body),
                 hashlib.sha256(body).hexdigest() if body else None, text, int(truncated), reason, now[:10], now),
            ).lastrowid
        self._audit.append(f"agent:{agent}", "research.fetch", {"fetch_id": fetch_id, "url": url, "outcome": outcome,
                                                                "reason": reason})
        return fetch_id


def _charset(content_type: str) -> str:
    for part in content_type.split(";")[1:]:
        name, _, value = part.strip().partition("=")
        if name.lower() == "charset" and value:
            return value.strip('"')
    return "utf-8"


def _deny_all() -> urllib.robotparser.RobotFileParser:
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    return parser
