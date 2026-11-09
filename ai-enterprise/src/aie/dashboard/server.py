"""Kommandocentralen: lokal server med standardbiblioteket (dashboard D1, FR-27, FR-28, D-073, D-078).

    py -m aie dashboard [--port 8765] [--lan]
    py -m aie dashboard set-code --founder Yorgo

- Lyssnar bara på 127.0.0.1 om inte `--lan` anges. Med `--lan` binds alla nätverkskort, och adressen som
  mobilen ska öppna skrivs ut.
- Alla sidor kräver inloggning med grundarens åtkomstkod (`auth.py`). Före inloggning ger varje sida 302
  till `/login`.
- Varje POST kräver sessionens CSRF-token.
- Gränssnittet ligger i `web/` och serveras härifrån, aldrig från det publika `docs/`.
- Data läses bara via kärnans funktioner. I D1 är det godkännandekön (`ApprovalQueue.pending`).
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
WEB = Path(__file__).resolve().parent / "web"
COOKIE = "aie_session"
MAX_BODY = 16 * 1024
DEFAULT_PORT = 8765

# (sökväg, menynamn, steget som fyller sidan, vad sidan ska visa)
PAGES = (
    ("/", "Home", "D2 and D5", "Capital, realized net profit, tax reserve, reserve, departments and live activity."),
    ("/departments", "Departments", "D3", "Every department as a building. A lit window is an agent at work."),
    ("/department", "Department", "D3", "The house: one room per agent, the meeting room, the archive and the task queue."),
    ("/agent", "Agent", "D3 and D6", "Status, mandate, performance, recent work and chat."),
    ("/finance", "Finance", "D5", "From sales to net profit, profit per day, the VAT limit, tax per track and the ledger."),
    ("/approvals", "Approvals", "D4", "The founders' queue with consultations and objections. Approve and reject."),
    ("/risk", "Risk and rules", "D5", "Mode, blocks in the control chain, limits and incidents."),
    ("/activity", "Activity log", "D2", "The full audit log with filters and a verified hash chain."),
    ("/settings", "Settings", "D7", "Notifications, founders and approval rules, AI models and access."),
)
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
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


def _money(minor: int, currency: str) -> str:
    return f"{minor / 100:,.2f} {currency}".replace(",", " ")


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
        if path.startswith("/static/"):
            return self._static(path.removeprefix("/static/"))
        session = self.dashboard.auth.session(self._sid())
        if path == "/login":
            return self._redirect("/") if session and session.founder else self._login_page()
        if session is None or session.founder is None:
            return self._redirect("/login")
        if path == "/api/ping":
            return self._send(200, json.dumps({"ok": True, "at": int(time.time())}).encode(), "application/json")
        page = next((p for p in PAGES if p[0] == path), None)
        if page is None:
            return self._html(404, self._shell(session, "Not found", "<p class='empty'>This page does not exist.</p>", ""))
        return self._html(200, self._page(session, page))

    def _static(self, name: str) -> None:
        target = (WEB / name).resolve()
        if WEB.resolve() not in target.parents or not target.is_file() or target.suffix == ".html":
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        kind = {".woff2": "font/woff2", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8"}.get(target.suffix) or mimetypes.guess_type(target.name)[0]
        self._send(200, target.read_bytes(), kind or "application/octet-stream")

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
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", "replace")).items()}
        sid = self._sid()
        session = self.dashboard.auth.session(sid)
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

    # --- Sidor -------------------------------------------------------------------------------

    def _page(self, session, page) -> str:
        path, name, step, purpose = page
        content = (f"<section class='card empty'><h2>{html.escape(name)}</h2><p>{html.escape(purpose)}</p>"
                   f"<p class='muted'>This page is filled in step {html.escape(step)}.</p></section>")
        if path == "/":
            content = self._home(step)
        return self._shell(session, name, content, path)

    def _home(self, step: str) -> str:
        try:
            pending = self.dashboard.pending_approvals()
            rows = "".join(
                f"<li class='approval' data-spotlight><span class='pill warn'>Pending</span>"
                f"<span class='what'>#{p['id']} {html.escape(p['kind'].capitalize())} on task {p['task']}</span>"
                f"<span class='amount' data-count='{p['amount_minor'] / 100:.2f}' data-decimals='2' "
                f"data-suffix=' {html.escape(p['currency'])}'>{html.escape(_money(p['amount_minor'], p['currency']))}</span>"
                f"<span class='muted'>from {html.escape(p['requested_by'])} · needs {p['required']} founder</span></li>"
                for p in pending)
            approvals = (f"<ul class='approvals' data-animated-list>{rows}</ul>" if pending
                         else "<p class='empty'>No approvals are waiting.</p>")
            count = len(pending)
        except Exception as exc:  # noqa: BLE001 — sidan ska visa att data saknas, inte krascha
            log.error("kunde inte läsa godkännandekön: %s", type(exc).__name__)
            approvals, count = "<p class='notice bad'>The approval queue could not be read (data missing).</p>", "–"
        count_attr = f" data-count='{count}'" if isinstance(count, int) else ""
        cards = "".join(
            f"<section class='card metric'><h3>{t}</h3><p class='value muted'>Missing</p>"
            f"<p class='muted'>Filled in step D5.</p></section>"
            for t in ("Capital", "Realized net profit", "Tax reserve", "Reserve"))
        return (f"<div class='metrics'>{cards}</div>"
                f"<section class='card'><h2>Pending approvals <span class='count'{count_attr}>{count}</span></h2>{approvals}"
                f"<p class='muted'>Read from the core approval queue. Approve and reject arrive in step D4.</p></section>"
                f"<section class='card empty'><h2>Live activity</h2><p class='muted'>Filled in step D2.</p></section>")

    def _shell(self, session, title: str, content: str, current: str) -> str:
        active = ' class="active" aria-current="page"'
        nav = "".join(f'<a href="{p}"{active if p == current else ""}>{html.escape(n)}</a>' for p, n, _, _ in PAGES)
        return _template("shell.html").substitute(
            title=html.escape(title), nav=nav, content=content, label=self.dashboard.label,
            founder=html.escape((session.founder or "").capitalize()), csrf=session.csrf,
            label_class="warn" if self.dashboard.label == "SIM" else "bad")


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
