"""Kommandocentralens server, inloggning och skal (dashboard D1): `aie.dashboard.server` och `auth`."""
from __future__ import annotations

import contextlib
import http.client
import io
import json
import re
import shutil
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode

from aie import runtime
from aie.audit import AuditLog
from aie.dashboard import server as srv
from aie.dashboard.auth import AuthError, Authenticator, read_env, set_code, verify_code
from aie.monitoring import shutdown_logging
from aie.simulation.seed import seed

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
CODE = "correct-horse-42"
FAKE_KEY = "gsk_fake_dashboard_test_key_123456"
PAGES = ("/", "/index.html", "/js/main.js", "/js/pages/overview.js", "/vendor/gsap/3.15.1/gsap.min.js")
API = ("/api/snapshot", "/api/health", "/api/me", "/api/github", "/api/ping")
FRONTEND = srv.FRONTEND


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.config_dir = cls.dir / "config"
        shutil.copytree(CONFIG, cls.config_dir)
        path = cls.config_dir / "system.toml"
        text = path.read_text(encoding="utf-8")
        text = text.replace('data_dir = "data"', f'data_dir = "{(cls.dir / "data").as_posix()}"')
        text = text.replace('log_dir = "logs"', f'log_dir = "{(cls.dir / "logs").as_posix()}"')
        path.write_text(text, encoding="utf-8")
        seed(cls.config_dir, days=2)
        cls.env_path = cls.dir / ".env"
        cls.env_path.write_text(f"GROQ_API_KEY={FAKE_KEY}\n", encoding="utf-8")
        set_code(cls.env_path, "Yorgo", CODE, ("robin", "yorgo"))
        cls.dashboard = srv.Dashboard(cls.config_dir, cls.env_path)
        cls.server = srv.make_server(cls.dashboard, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutdown_logging()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if cookie:
            headers["Cookie"] = cookie
        if body is not None:
            body = urlencode(body)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        return res, data

    @staticmethod
    def session_cookie(res):
        raw = res.getheader("Set-Cookie")
        if not raw:
            return None
        jar = SimpleCookie(raw)
        return f"{srv.COOKIE}={jar[srv.COOKIE].value}" if srv.COOKIE in jar else None

    def login_form(self):
        res, data = self.request("GET", "/login")
        self.assertEqual(res.status, 200)
        csrf = re.search(rb'name="csrf" value="([^"]+)"', data).group(1).decode()
        return self.session_cookie(res), csrf

    def login(self, founder="yorgo", code=CODE, address_reset=True):
        if address_reset:
            self.dashboard.auth._failures.clear()
        cookie, csrf = self.login_form()
        res, _ = self.request("POST", "/login", {"csrf": csrf, "founder": founder, "code": code}, cookie)
        return res, self.session_cookie(res) or cookie

    def csrf_of(self, cookie):
        _, data = self.request("GET", "/api/me", cookie=cookie)
        return json.loads(data)["csrf"]


class TestLogin(ServerCase):
    def test_pages_redirect_to_login_before_and_answer_200_after(self):
        """Verifies FR-27, FR-28: före inloggning ger sidan och skripten 302 till /login och API:t 401; efter 200.
        Bara de publika filerna i assets/ (CSS, typsnitt, ikoner) går att hämta före inloggning."""
        for path in PAGES:
            res, _ = self.request("GET", path)
            self.assertEqual((res.status, res.getheader("Location")), (302, "/login"), path)
        for path in API:
            res, _ = self.request("GET", path)
            self.assertEqual(res.status, 401, path)
        res, _ = self.request("GET", "/assets/css/app.css")
        self.assertEqual(res.status, 200)
        res, cookie = self.login()
        self.assertEqual((res.status, res.getheader("Location")), (302, "/"))
        for path in PAGES:
            res, _ = self.request("GET", path, cookie=cookie)
            self.assertEqual(res.status, 200, path)

    def test_wrong_code_is_denied(self):
        """Verifies FR-28: fel kod, okänd grundare och grundare utan kod nekas; ingen inloggad session skapas."""
        for founder, code in (("yorgo", "wrong-code-1"), ("mallory", CODE), ("robin", CODE), ("yorgo", "")):
            res, cookie = self.login(founder, code)
            self.assertEqual(res.status, 401, founder)
            res, _ = self.request("GET", "/", cookie=cookie)
            self.assertEqual(res.status, 302, founder)

    def test_lockout_after_five_failures(self):
        """Verifies FR-28: efter fem fel från samma adress nekas även rätt kod i 60 sekunder."""
        self.dashboard.auth._failures.clear()
        for _ in range(5):
            self.login("yorgo", "wrong-code-1", address_reset=False)
        res, _ = self.login("yorgo", CODE, address_reset=False)
        self.assertEqual(res.status, 401)
        self.dashboard.auth._failures.clear()

    def test_post_without_csrf_is_denied(self):
        """Verifies FR-28: POST utan eller med fel CSRF-token nekas med 403, både vid inloggning och utloggning."""
        cookie, csrf = self.login_form()
        for form in ({"founder": "yorgo", "code": CODE}, {"csrf": "x" + csrf, "founder": "yorgo", "code": CODE}):
            res, _ = self.request("POST", "/login", form, cookie)
            self.assertEqual(res.status, 403)
        res, _ = self.request("POST", "/login", {"csrf": csrf, "founder": "yorgo", "code": CODE})  # ingen cookie
        self.assertEqual(res.status, 403)
        _, session = self.login()
        res, _ = self.request("POST", "/logout", {}, session)
        self.assertEqual(res.status, 403)
        res, _ = self.request("GET", "/", cookie=session)
        self.assertEqual(res.status, 200)  # fortfarande inloggad
        res, _ = self.request("POST", "/logout", {"csrf": self.csrf_of(session)}, session)
        self.assertEqual((res.status, res.getheader("Location")), (302, "/login"))
        res, _ = self.request("GET", "/", cookie=session)
        self.assertEqual(res.status, 302)

    def test_session_cookie_is_httponly_and_samesite_strict(self):
        """Verifies FR-28: sessionscookien har HttpOnly och SameSite=Strict, och byts vid inloggning."""
        before, _ = self.login_form()
        res, after = self.login()
        raw = res.getheader("Set-Cookie")
        self.assertIn("HttpOnly", raw)
        self.assertIn("SameSite=Strict", raw)
        self.assertNotEqual(before, after)

    def test_logins_are_written_to_the_audit_log(self):
        """Verifies FR-28, §35: inloggningar och misslyckade försök loggas i revisionsloggen, utan koden."""
        self.login()
        self.login("yorgo", "wrong-code-1")
        with runtime._open(self.dashboard.config) as db:
            audit = AuditLog(db)
            entries = audit.entries()
            actions = [e.action for e in entries]
            self.assertIn("dashboard.login", actions)
            self.assertIn("dashboard.login_failed", actions)
            self.assertTrue(audit.verify().ok)
            self.assertNotIn(CODE, repr(entries))
            self.assertNotIn("wrong-code-1", repr(entries))


class TestBinding(ServerCase):
    def test_only_localhost_without_lan(self):
        """Verifies FR-27, D-073: utan --lan lyssnar servern bara på 127.0.0.1; med --lan på alla kort."""
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        local = srv.make_server(self.dashboard, port=0)
        self.addCleanup(local.server_close)
        self.assertEqual(local.server_address[0], "127.0.0.1")
        lan = srv.make_server(self.dashboard, port=0, lan=True)
        self.addCleanup(lan.server_close)
        self.assertEqual(lan.server_address[0], "0.0.0.0")


class TestNoSecrets(ServerCase):
    def test_no_secrets_in_any_response(self):
        """Verifies FR-28, SR-10: varken koden, hashen, saltet eller andra nycklar i .env syns i något svar."""
        stored = read_env(self.env_path)["AIE_DASHBOARD_CODE_YORGO"]
        _, _, salt, digest = stored.split("$")
        secrets_ = (CODE, stored, salt, digest, FAKE_KEY)
        _, cookie = self.login()
        responses = [self.request("GET", "/login")]
        responses += [self.request("GET", p, cookie=cookie) for p in (*PAGES, *API, "/assets/css/app.css", "/nope")]
        responses.append(self.login("yorgo", "wrong-code-1"))
        for res, data in responses:
            blob = (data if isinstance(data, bytes) else b"") + str(res.getheaders()).encode()
            for secret in secrets_:
                self.assertNotIn(secret.encode(), blob)

    def test_env_file_and_templates_are_not_served(self):
        """Verifies SR-10, FR-27: bara filer i web/ serveras; .env, mallarna och sökvägar utanför nekas."""
        _, cookie = self.login()
        for path in ("/assets/../../.env", "/assets/..%2F..%2F.env", "/js/../../.env", "/.env", "/login.html",
                     "/vendor/../../src/aie/dashboard/server.py", "/assets/../../../config/founders.toml"):
            res, _ = self.request("GET", path, cookie=cookie)
            self.assertIn(res.status, (404, 302), path)

    def test_security_headers(self):
        """Verifies FR-28: inga externa källor (CSP), ingen inramning och ingen cache av sidorna."""
        _, cookie = self.login()
        res, _ = self.request("GET", "/", cookie=cookie)
        self.assertIn("default-src 'self'", res.getheader("Content-Security-Policy"))
        self.assertEqual(res.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(res.getheader("Cache-Control"), "no-store")


class TestFrontend(ServerCase):
    def test_the_page_loads_with_the_shell(self):
        """Verifies FR-27, D-087: efter inloggning laddar sidan skalet: sidomeny, AGENTS, topprad med systemstatus,
        "Data as of", klocka, SIM-etikett, grundare, Pause agents och Kill switch."""
        _, cookie = self.login()
        res, data = self.request("GET", "/", cookie=cookie)
        page = data.decode("utf-8")
        self.assertEqual(res.status, 200)
        for needed in ('id="nav"', 'id="side-agents"', 'id="system-status"', "Data as of", 'id="clock"', 'id="env-label"',
                       'id="founder"', "Pause agents", "Kill switch", 'id="banner"', 'lang="en"', 'name="viewport"'):
            self.assertIn(needed, page)

    def test_all_ten_pages_exist_and_are_routed(self):
        """Verifies FR-27, D-087: de tio sidorna finns som moduler och är kopplade i routern."""
        main = (FRONTEND / "js" / "main.js").read_text(encoding="utf-8")
        for page in ("overview", "agents", "departments", "department", "agent", "approvals", "finance", "risk",
                     "activity", "settings"):
            module = FRONTEND / "js" / "pages" / f"{page}.js"
            self.assertTrue(module.is_file(), page)
            self.assertIn("export function view(", module.read_text(encoding="utf-8"), page)
            self.assertIn(f'import * as {page} from "./pages/{page}.js";', main)
        for label in ("Command center", "Agents", "Departments", "Approvals", "Finance", "Risk and rules", "Activity",
                      "Settings"):
            self.assertIn(f'nav: "{label}"', main)
        self.assertIn("SNAPSHOT_MS = 30_000", main)
        self.assertIn("GITHUB_MS = 60_000", main)
        self.assertIn("STALE_HOURS = 26", main)
        self.assertIn("Data is stale", main)

    def test_every_page_has_loading_empty_and_error_views(self):
        """Verifies FR-29: varje del ritas genom guard() (laddning och fel), och sidorna har tomvyer; saknad data
        visas som N/A, aldrig som 0."""
        common = (FRONTEND / "js" / "pages" / "common.js").read_text(encoding="utf-8")
        self.assertIn("skeleton(", common)
        self.assertIn("errorView(", common)
        ui = (FRONTEND / "js" / "ui.js").read_text(encoding="utf-8")
        self.assertIn("""export const NA = '<span class="na">N/A</span>'""", ui)
        self.assertIn("if (minor === null || minor === undefined || Number.isNaN(minor)) return NA;", ui)
        for page in (FRONTEND / "js" / "pages").glob("*.js"):
            if page.name == "common.js":
                continue
            text = page.read_text(encoding="utf-8")
            self.assertIn("guard(", text, page.name)
            self.assertRegex(text, r"emptyView\(|empty:", page.name)

    def test_css_uses_the_design_tokens_exactly(self):
        """Verifies D-087: varje token i DESIGN.md finns med exakt samma värde i app.css, och mobilbredden finns."""
        design = (ROOT / "docs" / "dashboard" / "DESIGN.md").read_text(encoding="utf-8")
        css = (FRONTEND / "assets" / "css" / "app.css").read_text(encoding="utf-8")
        tokens = re.findall(r"\| `(--[a-z0-9-]+)` \| `([^`]+)` \|", design)
        self.assertGreaterEqual(len(tokens), 20)
        for name, value in tokens:
            self.assertIn(f"{name}: {value};", css, name)
        self.assertIn("@media (max-width: 767px)", css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("letter-spacing: -0.035em", css)
        self.assertIn("letter-spacing: 0.14em", css)

    def test_no_inline_styles_or_scripts_and_nothing_external(self):
        """Verifies D-087, FR-28: inga inline-stilar eller inline-skript (CSP) och inga externa källor; allt laddas
        från den egna adressen."""
        index = (FRONTEND / "index.html").read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="([^"]+)"', index)
        self.assertTrue(refs)
        for ref in refs:
            self.assertTrue(ref.startswith("/") or ref.startswith("data:"), ref)
        self.assertNotIn("<script>", index)
        for f in [*(FRONTEND / "js").rglob("*.js"), FRONTEND / "index.html", FRONTEND / "assets" / "css" / "app.css"]:
            code = re.sub(r"(?m)^\s*//[^\n]*|/\*.*?\*/", "", f.read_text(encoding="utf-8"), flags=re.S)
            self.assertNotIn('style="', code, f.name)
            self.assertNotRegex(code, r"""(?:src=|href=|url\()["']?https?://""", f.name)

    def test_fonts_and_icons_are_local_with_licenses(self):
        """Verifies D-087: Geist och Geist Mono ligger lokalt med OFL, och Lucide-ikonerna som lokal sprite med ISC."""
        css = (FRONTEND / "assets" / "css" / "app.css").read_text(encoding="utf-8")
        urls = re.findall(r'url\("(\.\./fonts/[^"]+)"\)', css)
        self.assertEqual(len(urls), 6)
        for url in urls:
            path = (FRONTEND / "assets" / "css" / url).resolve()
            self.assertEqual(path.read_bytes()[:4], b"wOF2", url)
        self.assertIn("SIL Open Font License", (FRONTEND / "assets" / "fonts" / "OFL-Geist.txt").read_text(encoding="utf-8"))
        sprite = (FRONTEND / "assets" / "icons" / "lucide-sprite.svg").read_text(encoding="utf-8")
        self.assertGreaterEqual(sprite.count("<symbol"), 50)
        self.assertNotIn("<script", sprite.lower())
        self.assertIn("ISC License", (FRONTEND / "assets" / "icons" / "LICENSE-lucide.txt").read_text(encoding="utf-8"))
        js = "".join(p.read_text(encoding="utf-8") for p in (FRONTEND / "js").rglob("*.js"))
        used = set(re.findall(r'icon\("([a-z0-9-]+)"', js)) | set(re.findall(r"#i-([a-z0-9-]+)", js))
        used |= set(re.findall(r"#i-([a-z0-9-]+)", (FRONTEND / "index.html").read_text(encoding="utf-8")))
        used |= set(re.findall(r'icon: "([a-z0-9-]+)"', js))
        for name in sorted(used):
            if "$" in name:
                continue
            self.assertIn(f'id="i-{name}"', sprite, name)


class TestMotion(ServerCase):
    VENDOR = FRONTEND / "vendor"

    def test_vendor_files_are_unchanged_and_listed_with_source_and_license(self):
        """Verifies D-084: varje fil i vendor/ står i vendor/README.md med rätt SHA-256, och licenserna finns."""
        import hashlib

        readme = (self.VENDOR / "README.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| `([^`]+)` \|.*\| `([0-9a-f]{64})` \|$", readme, re.M)
        self.assertGreaterEqual(len(rows), 5)
        for name, digest in rows:
            self.assertEqual(hashlib.sha256((self.VENDOR / name).read_bytes()).hexdigest(), digest, name)
        self.assertIn("@license Copyright 2026, GreenSock", (self.VENDOR / "gsap/3.15.1/gsap.min.js").read_text(encoding="utf-8")[:300])
        self.assertIn("MIT License", (self.VENDOR / "lenis/1.3.27/LICENSE").read_text(encoding="utf-8"))
        self.assertIn("Commons Clause", (self.VENDOR / "react-bits/LICENSE.md").read_text(encoding="utf-8"))
        effects = (FRONTEND / "js" / "effects.js").read_text(encoding="utf-8")
        for credit in ("React Bits", "David Haz", "MIT + Commons Clause", "vendor/react-bits/LICENSE.md"):
            self.assertIn(credit, effects)

    def test_motion_is_short_and_respects_reduced_motion(self):
        """Verifies D-084, D-087: animationerna är 150–250 ms med ease-out och utan studs; prefers-reduced-motion
        stänger av dem, Lenis och radarns rörelse; Lenis aldrig på touch eller i tabeller, dialoger och chatt."""
        effects = (FRONTEND / "js" / "effects.js").read_text(encoding="utf-8")
        radar = (FRONTEND / "js" / "radar.js").read_text(encoding="utf-8")
        css = (FRONTEND / "assets" / "css" / "app.css").read_text(encoding="utf-8")
        code = re.sub(r"//[^\n]*", "", effects)
        self.assertNotRegex(code, r"(?i)bounce|elastic|back\.|spring|yoyo")
        for seconds in re.findall(r"duration:\s*([0-9.]+)", code):
            self.assertTrue(0.15 <= float(seconds) <= 0.25, seconds)
        self.assertIn("--t: 200ms;", css)
        self.assertIn("*, *::before, *::after { animation: none !important; transition: none !important; }", css)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)").matches) return;', radar)
        self.assertIn('"ontouchstart" in window || navigator.maxTouchPoints > 0', effects)
        self.assertIn("table, dialog, .table-wrap, .chat, .scroll-panel, [data-lenis-prevent]", effects)
        self.assertIn("onComplete: () => { el.textContent = final; }", effects)


class TestLocalStart(ServerCase):
    def test_busy_port_moves_to_the_next(self):
        """Verifies FR-27: är porten upptagen startar servern på nästa lediga i stället för att stoppa (Del 0)."""
        first = srv.bind(self.dashboard, 0, False)
        self.addCleanup(first.server_close)
        busy = first.server_address[1]
        second = srv.bind(self.dashboard, busy, False)
        self.addCleanup(second.server_close)
        self.assertNotEqual(second.server_address[1], busy)
        self.assertLess(second.server_address[1] - busy, srv.PORT_TRIES)
        self.assertEqual(second.server_address[0], "127.0.0.1")

    def test_has_code(self):
        """Verifies FR-28: has-code svarar 0 när grundaren har en kod och 1 annars, utan att skriva ut något."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(srv.has_code(self.config_dir, "Yorgo", self.env_path), 0)
            self.assertEqual(srv.has_code(self.config_dir, "Robin", self.env_path), 1)
            self.assertEqual(srv.has_code(self.config_dir, None, self.env_path), 0)
            self.assertEqual(srv.has_code(self.config_dir, None, self.dir / "missing.env"), 1)
        self.assertEqual(out.getvalue(), "")

    def test_dashboard_cmd_sets_everything_itself(self):
        """Verifies FR-27: dashboard.cmd sätter PYTHONPATH, hittar Python, sätter koden, skapar SIM-testdata
        och håller fönstret öppet vid fel, så att ett enda kommando räcker på Windows."""
        cmd = (ROOT / "dashboard.cmd").read_text(encoding="utf-8")
        for needed in ('cd /d "%~dp0"', 'set "PYTHONPATH=%~dp0src"', "where py", "dashboard has-code",
                       "dashboard set-code", "scripts\seed_sim.py", "dashboard --open %*", "pause"):
            self.assertIn(needed, cmd)


class TestLocalApi(ServerCase):
    def test_local_api_has_the_same_shape_and_requires_login(self):
        """Verifies FR-27, FR-29, D-085: den lokala servern svarar på /api/snapshot och /api/health som
        Cloudflare-funktionerna, med samma snapshot-schema, och bara efter inloggning."""
        for path in ("/api/snapshot", "/api/health", "/api/github"):
            res, _ = self.request("GET", path)
            self.assertEqual(res.status, 401, path)
        _, cookie = self.login()
        res, data = self.request("GET", "/api/snapshot", cookie=cookie)
        self.assertEqual(res.status, 200)
        snap = json.loads(data)
        self.assertEqual(snap["schema"], "aie.snapshot/1")
        self.assertEqual(len([a for a in snap["approvals"]["items"] if a["status"] == "pending"]), 3)
        self.assertEqual(res.getheader("Cache-Control"), "no-store")
        res, data = self.request("GET", "/api/health", cookie=cookie)
        self.assertEqual(json.loads(data)["status"], "ok")
        res, _ = self.request("GET", "/api/github", cookie=cookie)
        self.assertEqual(res.status, 503)


class TestSetCode(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Path(tmp.name) / ".env"

    def test_only_a_hash_is_stored_and_other_lines_are_kept(self):
        """Verifies FR-28, SR-10: set-code sparar bara en hash i .env, ersätter en gammal och lämnar andra rader."""
        self.env.write_text("GROQ_API_KEY=abc\n", encoding="utf-8")
        set_code(self.env, "Yorgo", "first-code-1", ("robin", "yorgo"))
        set_code(self.env, "yorgo", CODE, ("robin", "yorgo"))
        text = self.env.read_text(encoding="utf-8")
        self.assertNotIn(CODE, text)
        self.assertNotIn("first-code-1", text)
        self.assertEqual(text.count("AIE_DASHBOARD_CODE_YORGO="), 1)
        self.assertIn("GROQ_API_KEY=abc", text)
        self.assertTrue(verify_code(CODE, read_env(self.env)["AIE_DASHBOARD_CODE_YORGO"]))
        self.assertFalse(verify_code("first-code-1", read_env(self.env)["AIE_DASHBOARD_CODE_YORGO"]))

    def test_unknown_founder_and_short_code_are_refused(self):
        """Verifies FR-28: okänd grundare och för kort kod nekas, och ingenting skrivs."""
        with self.assertRaises(AuthError):
            set_code(self.env, "Mallory", CODE, ("robin", "yorgo"))
        with self.assertRaises(AuthError):
            set_code(self.env, "Robin", "short", ("robin", "yorgo"))
        self.assertFalse(self.env.exists())

    def test_command_never_prints_the_code(self):
        """Verifies FR-28, SR-10: kommandot frågar två gånger, skriver aldrig ut koden och nekar olika koder."""
        out, err = io.StringIO(), io.StringIO()
        answers = iter([CODE, CODE])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = srv.set_code_command(CONFIG, "Robin", read=lambda _: next(answers), env_path=self.env)
        shutdown_logging()
        self.assertEqual(code, 0, err.getvalue())
        self.assertNotIn(CODE, out.getvalue() + err.getvalue())
        self.assertIn("AIE_DASHBOARD_CODE_ROBIN=", self.env.read_text(encoding="utf-8"))
        answers = iter([CODE, CODE + "x"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(srv.set_code_command(CONFIG, "Robin", read=lambda _: next(answers), env_path=self.env), 1)
        shutdown_logging()

    def test_authenticator_sessions_expire(self):
        """Verifies FR-28: en session gäller i 12 timmar och försvinner sedan."""
        now = [1000.0]
        auth = Authenticator(self.env, ("robin", "yorgo"), clock=lambda: now[0])
        sid, _ = auth.new_session("yorgo")
        self.assertIsNotNone(auth.session(sid))
        now[0] += 12 * 3600 + 1
        self.assertIsNone(auth.session(sid))


if __name__ == "__main__":
    unittest.main()
