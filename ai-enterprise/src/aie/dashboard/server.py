"""Command Center lokalt: samma gränssnitt och samma API-form som på Cloudflare, utan internet (D-085, D1).

    py -m aie dashboard [--port 8765] [--lan] [--open]      (eller ai-enterprise/dashboard.cmd på Windows)
    py -m aie dashboard set-code --founder Yorgo

- Lyssnar bara på 127.0.0.1 om inte `--lan` anges. Med `--lan` binds alla nätverkskort, och adressen som
  mobilen ska öppna skrivs ut.
- Inloggning med grundarens åtkomstkod (`auth.py`). Före inloggning ger allt utom inloggningssidan och de
  publika filerna i `assets/` 302 till `/login` (sidor) eller 401 (API).
- Varje POST kräver sessionens CSRF-token.
- Gränssnittet är `ai-enterprise/command-center/` (samma filer som Cloudflare Pages publicerar). API:t
  (`/api/snapshot`, `/api/health`, `/api/me`, `/api/github`) har samma form som `command-center/functions/api/`.
- Data läses bara via kärnans funktioner (snapshoten).
"""
from __future__ import annotations

import getpass
import html
import json
import mimetypes
import socket
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, urlsplit

from .. import runtime
from ..monitoring import get_logger
from .auth import AuthError, Authenticator, set_code

log = get_logger("dashboard")
WEB = Path(__file__).resolve().parent / "web"  # bara inloggningssidan
FRONTEND = Path(__file__).resolve().parents[3] / "command-center" / "public"  # samma filer som Cloudflare Pages publicerar
PUBLIC_PREFIXES = ("/assets/",)  # typsnitt, ikoner och CSS: inga data, behövs av inloggningssidan
PRIVATE_PREFIXES = ("/js/", "/vendor/")
COOKIE = "aie_session"
MAX_BODY = 16 * 1024
DEFAULT_PORT = 8765

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class Dashboard:
    """Det som servern behöver: konfiguration, inloggning och läsning via kärnan."""

    def __init__(self, config_dir: Path, env_path: Path | None = None) -> None:
        self.config_dir = Path(config_dir)
        self.config = runtime._load(self.config_dir, console=False)
        self.founders = tuple(self.config.system.founders)
        self.env_path = env_path or self.config_dir.resolve().parent / ".env"
        self.auth = Authenticator(self.env_path, self.founders)
        self.label = "SIM" if self.config.system.environment == "sim" else "REAL"
        self._db_lock = threading.Lock()  # SQLite: en läsare i taget räcker lokalt

    def pending_approvals(self) -> list[dict]:
        """De väntande godkännandena, lästa via kärnans kö (FR-29, FR-31)."""
        from ..governance.cli import build

        with self._db_lock, runtime._open(self.config) as db:
            queue = build(self.config, db, self.config_dir).queue
            return [{"id": r.request_id, "kind": r.kind.value, "task": r.task_id, "amount_minor": r.amount_minor,
                     "currency": r.currency, "required": r.required_approvals, "requested_by": r.requested_by,
                     "reason": r.reason} for r in queue.pending()]

    def snapshot(self) -> dict:
        """Samma snapshot som `py -m aie publish` laddar upp, men byggd ur den lokala databasen (Del 1)."""
        from ..simulation.market import SimClock
        from ..simulation.run import stored_run
        from ..system import build_system
        from .snapshot import build_snapshot

        with self._db_lock, runtime._open(self.config) as db:
            run = stored_run(db)
            system = build_system(self.config, db, self.config_dir, clock=SimClock(run["start_date"]) if run else None)
            return build_snapshot(system, self.config, self.config_dir)

    def act(self, founder: str, body: dict) -> dict:
        """Ett knapptryck lokalt: samma validering och samma kärnanrop som kön i molnet (control.process)."""
        import secrets
        from datetime import UTC

        from . import control

        item = {**{k: v for k, v in body.items() if k not in ("id", "founder", "at")},
                "id": f"local-{secrets.token_hex(8)}", "founder": founder, "at": datetime.now(UTC).isoformat()}
        with self._db_lock, runtime._open(self.config) as db:
            system, gov = control.open_core(self.config, db, self.config_dir)
            return control.process(system, gov, [(item["id"], json.dumps(item).encode("utf-8"))], self.founders)

    def audit(self, actor: str, action: str, details: dict) -> None:
        """Inloggningar loggas i revisionsloggen (FR-28, §35). Aldrig koden."""
        from ..audit import AuditLog

        try:
            with self._db_lock, runtime._open(self.config) as db:
                AuditLog(db).append(actor, action, details)
        except Exception as exc:  # noqa: BLE001 — en loggning som misslyckas får inte stoppa servern
            log.error("kunde inte logga %s: %s", action, type(exc).__name__)


def _template(name: str) -> Template:
    return Template((WEB / name).read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    server_version = "aie-dashboard"
    sys_version = ""
    dashboard: Dashboard  # sätts av make_server

    def log_message(self, fmt: str, *args) -> None:  # ingen åtkomstlogg med frågesträngar på stderr
        log.debug("http %s", self.requestline.split(" ")[0] if self.requestline else "-")

    # --- Svar --------------------------------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, status: int, text: str, headers: dict | None = None) -> None:
        self._send(status, text.encode("utf-8"), "text/html; charset=utf-8", headers)

    def _redirect(self, location: str, headers: dict | None = None) -> None:
        self._send(HTTPStatus.FOUND, b"", "text/plain; charset=utf-8", {"Location": location, **(headers or {})})

    def _cookie(self, sid: str) -> dict:
        return {"Set-Cookie": f"{COOKIE}={sid}; HttpOnly; SameSite=Strict; Path=/"}

    def _sid(self) -> str | None:
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        return jar[COOKIE].value if COOKIE in jar else None

    # --- GET ---------------------------------------------------------------------------------

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith(PUBLIC_PREFIXES):
            return self._file(FRONTEND, path.lstrip("/"))
        session = self.dashboard.auth.session(self._sid())
        if path == "/login":
            return self._redirect("/") if session and session.founder else self._login_page()
        if session is None or session.founder is None:
            if path.startswith("/api/"):
                return self._send(401, b'{"error":"unauthorized"}', "application/json")
            return self._redirect("/login")
        if path == "/api/ping":
            return self._send(200, json.dumps({"ok": True, "at": int(time.time())}).encode(), "application/json")
        if path == "/api/me":
            body = {"email": None, "founder": session.founder, "mode": "local", "csrf": session.csrf}
            return self._send(200, json.dumps(body).encode(), "application/json")
        if path in ("/api/snapshot", "/api/health"):
            return self._api(path)
        if path == "/api/github":  # lokalt finns ingen läs-token; gränssnittet visar felvyn
            return self._send(503, b'{"error":"github unavailable offline"}', "application/json")
        if path.startswith("/api/"):
            return self._send(404, b'{"error":"not found"}', "application/json")
        if path in ("/", "/index.html"):
            return self._file(FRONTEND, "index.html")
        if path.startswith(PRIVATE_PREFIXES):
            return self._file(FRONTEND, path.lstrip("/"))
        return self._send(404, b"not found", "text/plain; charset=utf-8")

    def _file(self, root: Path, name: str) -> None:
        target = (root / name).resolve()
        if root.resolve() not in target.parents or not target.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        kind = {".woff2": "font/woff2", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".svg": "image/svg+xml", ".html": "text/html; charset=utf-8"}.get(target.suffix)             or mimetypes.guess_type(target.name)[0]
        self._send(200, target.read_bytes(), kind or "application/octet-stream")

    def _api(self, path: str) -> None:
        """Samma form som Cloudflare-funktionerna (functions/api/), så att samma gränssnitt fungerar lokalt."""
        try:
            snap = self.dashboard.snapshot()
        except Exception as exc:  # noqa: BLE001 — felvyn i gränssnittet, aldrig en krasch
            log.error("snapshot kunde inte byggas lokalt: %s", type(exc).__name__)
            return self._send(503, b'{"error":"snapshot unavailable"}', "application/json")
        if path == "/api/snapshot":
            return self._send(200, json.dumps(snap, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        body = {"status": "ok", "version": snap["system"]["version"]["value"], "snapshot_generated_at": snap["generated_at"],
                "snapshot_age_seconds": 0, "mode": "local"}
        return self._send(200, json.dumps(body).encode(), "application/json")

    def _login_page(self, error: str = "", status: int = 200) -> None:
        sid = self._sid()
        session = self.dashboard.auth.session(sid)
        if session is None or session.founder is not None:  # före inloggning: en session bara för CSRF
            sid, session = self.dashboard.auth.new_session()
        options = "".join(f'<option value="{html.escape(f)}">{html.escape(f.capitalize())}</option>'
                          for f in self.dashboard.founders)
        configured = self.dashboard.auth.configured()
        hint = "" if configured else (
            "<p class='notice warn'>No access code is set yet. Run "
            "<code>py -m aie dashboard set-code --founder Yorgo</code> in a terminal first.</p>")
        body = _template("login.html").substitute(
            csrf=session.csrf, options=options, label=self.dashboard.label,
            error=f"<p class='notice bad' role='alert'>{html.escape(error)}</p>" if error else "", hint=hint)
        self._html(status, body, self._cookie(sid))

    # --- POST --------------------------------------------------------------------------------

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, b"too large", "text/plain; charset=utf-8")
        raw = self.rfile.read(length)
        sid = self._sid()
        session = self.dashboard.auth.session(sid)
        if path.startswith("/api/"):
            return self._api_post(path, raw, session)
        if path == "/logout" and session and session.founder and self.headers.get("X-CSRF-Token") == session.csrf:
            self.dashboard.auth.end(sid)  # knappen "Log out" i toppraden (samma anrop som i molnet)
            self.dashboard.audit(session.founder, "dashboard.logout", {})
            return self._send(200, b'{"ok":true}', "application/json",
                              {"Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
        if session is None or not form.get("csrf") or form.get("csrf") != session.csrf:
            log.warning("POST %s utan giltig CSRF-token nekades", path)
            return self._send(403, b"Forbidden: missing or invalid CSRF token", "text/plain; charset=utf-8")
        if path == "/login":
            return self._login(sid, form)
        if session.founder is None:
            return self._redirect("/login")
        if path == "/logout":
            self.dashboard.auth.end(sid)
            self.dashboard.audit(session.founder, "dashboard.logout", {})
            return self._redirect("/login", {"Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        return self._send(404, b"not found", "text/plain; charset=utf-8")

    def _api_post(self, path: str, raw: bytes, session) -> None:
        """Samma form som functions/api/action.js och chat.js. Lokalt finns ingen kö: beslutet valideras och
        utförs direkt med samma kod som `aie control ingest` (kärnans funktioner, revisionsloggen)."""
        def reply(status: int, body: dict) -> None:
            self._send(status, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        if session is None or session.founder is None:
            return reply(401, {"error": "unauthorized"})
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return reply(403, {"error": "cross-origin request refused"})
        if self.headers.get("X-Command-Center") != "1" or self.headers.get("X-CSRF-Token") != session.csrf:
            log.warning("POST %s utan giltig header eller CSRF-token nekades", path)
            return reply(403, {"error": "missing header or CSRF token"})
        if path == "/api/chat":
            return reply(503, {"error": "chat needs the cloud deployment (Groq); it is not available offline"})
        if path != "/api/action":
            return reply(404, {"error": "not found"})
        try:
            body = json.loads(raw or b"null")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return reply(400, {"error": "invalid json"})
        try:
            result = self.dashboard.act(session.founder, body)
        except Exception as exc:  # noqa: BLE001
            log.error("lokal åtgärd misslyckades: %s", type(exc).__name__)
            return reply(500, {"error": "the action could not be applied"})
        if result["rejected"]:
            return reply(400, {"error": result["rejected"][0]["reason"]})
        return reply(202, {"id": result["applied"][0]["id"], "queued": False, "applied": True})

    def _login(self, old_sid: str | None, form: dict) -> None:
        address = self.client_address[0]
        founder = self.dashboard.auth.login(address, form.get("founder", ""), form.get("code", ""))
        if founder is None:
            locked = self.dashboard.auth.locked(address)
            self.dashboard.audit("dashboard", "dashboard.login_failed",
                                 {"founder": form.get("founder", "")[:20], "locked": locked})
            message = "Too many attempts. Wait a minute." if locked else "Wrong founder or access code."
            return self._login_page(message, 401)
        self.dashboard.auth.end(old_sid)  # ny session vid inloggning
        sid, _ = self.dashboard.auth.new_session(founder)
        self.dashboard.audit(founder, "dashboard.login", {})
        self._redirect("/", self._cookie(sid))


class ExclusiveServer(ThreadingHTTPServer):
    """På Windows låter SO_REUSEADDR en andra server ta en port som redan används, och då hamnar anropen
    slumpvis hos någon av dem. Här binds porten exklusivt, så att en upptagen port faktiskt ger fel (Del 0)."""

    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(dashboard: Dashboard, port: int = DEFAULT_PORT, lan: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"dashboard": dashboard})
    server = ExclusiveServer(("0.0.0.0" if lan else "127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def lan_address() -> str:
    """Datorns adress i det lokala nätet. UDP-anslutningen skickar inga paket."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.168.0.1", 9))
            return s.getsockname()[0]
        except OSError:
            return socket.gethostbyname(socket.gethostname())


PORT_TRIES = 10


def bind(dashboard: Dashboard, port: int, lan: bool) -> ThreadingHTTPServer:
    """Försöker porten och de nio närmaste. En upptagen port var en orsak till att D1 inte startade (Del 0)."""
    last: OSError | None = None
    for candidate in range(port, port + PORT_TRIES):
        try:
            return make_server(dashboard, candidate, lan)
        except OSError as exc:
            last = exc
    raise OSError(f"portarna {port}–{port + PORT_TRIES - 1} är upptagna ({last})")


def serve(config_dir: Path, port: int = DEFAULT_PORT, lan: bool = False, open_browser: bool = False) -> int:
    try:
        dashboard = Dashboard(config_dir)
    except runtime.StartupError as exc:
        return runtime._fail(exc)
    try:
        server = bind(dashboard, port, lan)
    except OSError as exc:
        print(f"FEL: kunde inte starta: {exc}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Command center ({dashboard.label}) is running at {url}")
    if server.server_address[1] != port:
        print(f"(port {port} was busy, so {server.server_address[1]} is used)")
    if lan:
        print(f"On your phone (same Wi-Fi): http://{lan_address()}:{server.server_address[1]}/")
    if not dashboard.auth.configured():
        print("No access code is set. Run: py -m aie dashboard set-code --founder Yorgo")
    print("Keep this window open. Stop with Ctrl+C.")
    if open_browser:
        import webbrowser

        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def has_code(config_dir: Path, founder: str | None = None, env_path: Path | None = None) -> int:
    """0 om en kod finns (för grundaren, eller för någon om ingen anges), annars 1. Skriver aldrig ut hashen."""
    try:
        config = runtime._load(Path(config_dir), console=False)
    except runtime.StartupError as exc:
        return runtime._fail(exc)
    auth = Authenticator(env_path or Path(config_dir).resolve().parent / ".env", tuple(config.system.founders))
    configured = auth.configured()
    return 0 if (founder.strip().lower() in configured if founder else configured) else 1


def _read_code(prompt: str) -> str:
    """getpass döljer koden. Fungerar den inte i terminalen (t.ex. Git Bash) används vanlig inmatning med varning."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError, OSError):
            print("(this terminal cannot hide input; the code will be visible while you type)")
            return input(prompt)


def set_code_command(config_dir: Path, founder: str, read=_read_code, env_path: Path | None = None) -> int:
    """Frågar efter koden två gånger (visas inte på skärmen) och sparar bara hashen i `.env`."""
    try:
        config = runtime._load(Path(config_dir), console=False)
    except runtime.StartupError as exc:
        return runtime._fail(exc)
    path = env_path or Path(config_dir).resolve().parent / ".env"
    first = read(f"New access code for {founder} (at least 8 characters): ")
    if read("Repeat the code: ") != first:
        print("FEL: koderna är inte lika", file=sys.stderr)
        return 1
    try:
        set_code(path, founder, first, tuple(config.system.founders))
    except AuthError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    print(f"Koden för {founder} är sparad som hash i {path} ({datetime.now():%Y-%m-%d %H:%M}).")
    return 0
