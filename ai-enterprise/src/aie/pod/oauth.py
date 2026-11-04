"""Koppla konton: OAuth 2 för Etsy, Pinterest och Instagram (arbetsorder 04, D-068).

`python -m aie connect etsy|pinterest|instagram` kör flödet så här:

1. **PKCE** (RFC 7636, S256) och ett slumpat `state` skapas för varje försök. Etsy kräver PKCE. Det skadar inte hos de andra.
2. **Webbläsaren** öppnar tjänstens sida för medgivande. Grundaren loggar in och godkänner själv, och koden ser aldrig lösenordet.
3. **Tillbaka:** tjänsten skickar webbläsaren till `redirect_uri`. Är det `http://127.0.0.1:<port>/callback` tar en lokal server på 127.0.0.1 emot koden, en gång, och stänger sedan. Etsy och Meta kräver en https-adress. Då klistrar grundaren in adressen från webbläsarens adressfält (`--paste`). `state` kontrolleras i båda fallen.
4. **Token:** koden byts mot en token, som sparas med `TokenStore`, **utanför repot**:
   - mappen är `~/.config/aie/tokens/` eller `AIE_TOKEN_DIR`, med filrättigheter 600
   - inget skrivs ut och inget loggas
   - en mapp inuti repot vägras

Adresser och scopes står i `SERVICES`:
- Etsy är verifierat mot developer.etsy.com 2026-11-04.
- Pinterest och Instagram följer deras dokumentation. Det verifieras vid första kopplingen, eftersom inga konton finns än.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import stat
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from .http import JsonClient, Transport, urllib_transport

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # ai-enterprise/; tokens får aldrig hamna under repots rot


@dataclass(frozen=True, slots=True)
class Service:
    name: str
    authorize_url: str
    token_base: str  # https-bas för tokenanropet
    token_path: str
    scopes: tuple[str, ...]
    client_id_env: str
    client_secret_env: str | None  # None: offentlig klient med PKCE (Etsy)
    redirect_env: str
    verified: str


SERVICES = {
    "etsy": Service("etsy", "https://www.etsy.com/oauth/connect", "https://api.etsy.com", "/v3/public/oauth/token",
                    ("listings_r", "listings_w", "shops_r", "transactions_r"), "ETSY_API_KEY", None,
                    "ETSY_REDIRECT_URI", "developer.etsy.com/documentation/essentials/authentication, 2026-11-04"),
    "pinterest": Service("pinterest", "https://www.pinterest.com/oauth/", "https://api.pinterest.com",
                         "/v5/oauth/token", ("boards:read", "pins:read", "pins:write", "user_accounts:read"),
                         "PINTEREST_APP_ID", "PINTEREST_APP_SECRET", "PINTEREST_REDIRECT_URI",
                         "enligt developers.pinterest.com; verifieras vid första kopplingen"),
    "instagram": Service("instagram", "https://www.instagram.com/oauth/authorize", "https://api.instagram.com",
                         "/oauth/access_token", ("instagram_business_basic", "instagram_business_content_publish"),
                         "INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "INSTAGRAM_REDIRECT_URI",
                         "enligt developers.facebook.com (Instagram Login); verifieras vid första kopplingen"),
}


# --- PKCE och adresser ---------------------------------------------------------------------------

def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]  # 43–128 tecken ur [A-Za-z0-9-._~]
    return verifier, challenge(verifier)


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorize_url(service: Service, client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    keystring = client_id.split(":", 1)[0]  # Etsys x-api-key är keystring:shared_secret; bara keystring här
    query = {"response_type": "code", "client_id": keystring, "redirect_uri": redirect_uri,
             "scope": " ".join(service.scopes) if service.name == "etsy" else ",".join(service.scopes),
             "state": state, "code_challenge": code_challenge, "code_challenge_method": "S256"}
    return f"{service.authorize_url}?{urllib.parse.urlencode(query, quote_via=urllib.parse.quote)}"


def parse_redirect(url: str, expected_state: str) -> str:
    """Koden ur adressen tjänsten skickade tillbaka till. Kastar ValueError vid fel state eller ett nej."""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url.strip()).query)
    if "error" in query:
        raise ValueError(f"tjänsten svarade nej: {query['error'][0]}")
    if query.get("state", [""])[0] != expected_state:
        raise ValueError("state stämmer inte; försöket avbryts (skydd mot förfalskade svar)")
    code = query.get("code", [""])[0]
    if not code:
        raise ValueError("adressen innehåller ingen kod")
    return code


def wait_for_callback(port: int, expected_state: str, timeout: float = 300.0) -> str:
    """Tar emot en enda omdirigering på http://127.0.0.1:<port>/callback och returnerar koden."""
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            try:
                result["code"] = parse_redirect(f"http://127.0.0.1{self.path}", expected_state)
                body, status = "Kontot är kopplat. Du kan stänga fliken.", 200
            except ValueError as exc:
                result["error"] = str(exc)
                body, status = f"Kopplingen misslyckades: {exc}", 400
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *args):  # inget i loggen: adressen innehåller koden
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = timeout
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout + 1)
    server.server_close()
    if "error" in result:
        raise ValueError(result["error"])
    if "code" not in result:
        raise TimeoutError("ingen omdirigering kom inom tidsgränsen")
    return result["code"]


def exchange_code(service: Service, environ, redirect_uri: str, code: str, verifier: str,
                  transport: Transport = urllib_transport) -> dict:
    client_id = environ.get(service.client_id_env, "")
    form = {"grant_type": "authorization_code", "client_id": client_id.split(":", 1)[0], "redirect_uri": redirect_uri,
            "code": code, "code_verifier": verifier}
    headers = {}
    secret = environ.get(service.client_secret_env, "") if service.client_secret_env else ""
    if service.name == "pinterest":  # Pinterest vill ha klientens id och hemlighet som Basic-rubrik
        basic = base64.b64encode(f"{form.pop('client_id')}:{secret}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {basic}"
    elif secret:
        form["client_secret"] = secret
    client = JsonClient(service.token_base, {}, transport=transport, retries=1, min_interval=0)
    return client.post_form(service.token_path, form, headers)


# --- Tokens utanför repot ------------------------------------------------------------------------

class TokenStore:
    def __init__(self, directory: Path | str | None = None, environ=os.environ) -> None:
        base = Path(directory or environ.get("AIE_TOKEN_DIR") or Path.home() / ".config" / "aie" / "tokens")
        base = base.expanduser().resolve()
        repo = PROJECT_ROOT.parent.resolve()
        if base == repo or repo in base.parents:
            raise ValueError("token-mappen får inte ligga i repot (SR-10)")
        self.directory = base

    def __repr__(self) -> str:
        return f"TokenStore({str(self.directory)!r})"

    def path(self, service: str) -> Path:
        if service not in SERVICES:
            raise ValueError(f"okänd tjänst {service!r}")
        return self.directory / f"{service}.json"

    def save(self, service: str, token: dict) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(service)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(token, f)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return path

    def load(self, service: str) -> dict | None:
        path = self.path(service)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def access_token(self, service: str, environ=os.environ) -> str | None:
        """Token från miljön (GitHub-hemlighet, t.ex. PINTEREST_ACCESS_TOKEN) eller från filen."""
        env = environ.get(f"{service.upper()}_ACCESS_TOKEN")
        if env:
            return env
        token = self.load(service)
        return token.get("access_token") if token else None


def connect(service_name: str, environ=os.environ, *, port: int = 8765, paste: bool = False, store: TokenStore | None = None,
            open_browser=None, read_line=input, transport: Transport = urllib_transport) -> Path:
    """Hela flödet. Returnerar sökvägen till token-filen; själva token skrivs aldrig ut."""
    service = SERVICES[service_name]
    client_id = environ.get(service.client_id_env)
    if not client_id:
        raise ValueError(f"{service.client_id_env} saknas; se docs/setup-konton.md")
    if service.client_secret_env and not environ.get(service.client_secret_env):
        raise ValueError(f"{service.client_secret_env} saknas; se docs/setup-konton.md")
    redirect_uri = environ.get(service.redirect_env) or f"http://127.0.0.1:{port}/callback"
    if service.name in ("etsy", "instagram") and not redirect_uri.startswith("https://"):
        paste = True  # Etsy och Meta tar bara https-adresser; koden klistras in i stället
    verifier, code_challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    url = authorize_url(service, client_id, redirect_uri, state, code_challenge)
    print(f"Öppna adressen, logga in hos {service.name} och godkänn:\n{url}")
    if open_browser is not None:
        open_browser(url)
    if paste or not redirect_uri.startswith("http://127.0.0.1"):
        code = parse_redirect(read_line("Klistra in adressen från webbläsarens adressfält: "), state)
    else:
        code = wait_for_callback(int(urllib.parse.urlsplit(redirect_uri).port or port), state)
    token = exchange_code(service, environ, redirect_uri, code, verifier, transport)
    if not isinstance(token, dict) or "access_token" not in token:
        raise ValueError("tjänsten gav ingen token")
    return (store or TokenStore(environ=environ)).save(service.name, token)
