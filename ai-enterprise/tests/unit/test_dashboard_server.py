"""Kommandocentralens server, inloggning och skal (dashboard D1): `aie.dashboard.server` och `auth`."""
from __future__ import annotations

import contextlib
import http.client
import io
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
PAGES = ("/", "/departments", "/department", "/agent", "/finance", "/approvals", "/risk", "/activity", "/settings")


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
        _, data = self.request("GET", "/", cookie=cookie)
        return re.search(rb'name="csrf" value="([^"]+)"', data).group(1).decode()


class TestLogin(ServerCase):
    def test_pages_redirect_to_login_before_and_answer_200_after(self):
        """Verifies FR-27, FR-28: före inloggning ger alla nio sidor 302 till /login, efter inloggning 200."""
        for path in (*PAGES, "/api/ping"):
            res, _ = self.request("GET", path)
            self.assertEqual((res.status, res.getheader("Location")), (302, "/login"), path)
        res, cookie = self.login()
        self.assertEqual((res.status, res.getheader("Location")), (302, "/"))
        for path in (*PAGES, "/api/ping"):
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
        responses += [self.request("GET", p, cookie=cookie) for p in (*PAGES, "/api/ping", "/static/app.css",
                                                                      "/static/app.js", "/nope")]
        responses.append(self.login("yorgo", "wrong-code-1"))
        for res, data in responses:
            blob = (data if isinstance(data, bytes) else b"") + str(res.getheaders()).encode()
            for secret in secrets_:
                self.assertNotIn(secret.encode(), blob)

    def test_env_file_and_templates_are_not_served(self):
        """Verifies SR-10, FR-27: bara filer i web/ serveras; .env, mallarna och sökvägar utanför nekas."""
        _, cookie = self.login()
        for path in ("/static/../../../.env", "/static/..%2F..%2F.env", "/static/shell.html", "/.env",
                     "/static/login.html", "/static/fonts/../../server.py"):
            res, _ = self.request("GET", path, cookie=cookie)
            self.assertIn(res.status, (404, 302), path)

    def test_security_headers(self):
        """Verifies FR-28: inga externa källor (CSP), ingen inramning och ingen cache av sidorna."""
        _, cookie = self.login()
        res, _ = self.request("GET", "/", cookie=cookie)
        self.assertIn("default-src 'self'", res.getheader("Content-Security-Policy"))
        self.assertEqual(res.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(res.getheader("Cache-Control"), "no-store")


class TestShell(ServerCase):
    def test_shell_has_nine_pages_labels_and_inactive_controls(self):
        """Verifies FR-27, D-073: skalet har alla nio sidor, Live-indikator, SIM-etikett, klocka och
        inaktiva knappar för paus och nödstopp med texten "Available in D5"."""
        _, cookie = self.login()
        _, data = self.request("GET", "/", cookie=cookie)
        page = data.decode("utf-8")
        for path, name, _, _ in srv.PAGES:
            self.assertIn(f'href="{path}"', page)
            self.assertIn(f">{name}</a>", page)
        self.assertEqual(len(srv.PAGES), 9)
        self.assertIn('id="live"', page)
        self.assertIn(">SIM</span>", page)
        self.assertIn('id="clock"', page)
        for button in ("Pause agents", "Kill switch"):
            self.assertRegex(page, rf'<button[^>]*disabled[^>]*>{button}<span class="sub">Available in D5</span>')
        self.assertIn('lang="en"', page)
        self.assertIn('name="viewport"', page)

    def test_every_page_has_an_empty_state_naming_its_step(self):
        """Verifies FR-29: varje sida utom Home visar en tom vy som säger vilket steg som fyller den."""
        _, cookie = self.login()
        for path, name, step, _ in srv.PAGES[1:]:
            _, data = self.request("GET", path, cookie=cookie)
            self.assertIn(f"This page is filled in step {step}.", data.decode("utf-8"), path)

    def test_home_shows_the_three_pending_approvals_from_the_core_queue(self):
        """Verifies FR-29, FR-31: Home visar de 3 väntande godkännandena ur seed-datan, lästa via kärnans kö."""
        _, cookie = self.login()
        _, data = self.request("GET", "/", cookie=cookie)
        page = data.decode("utf-8")
        pending = self.dashboard.pending_approvals()
        self.assertEqual(len(pending), 3)
        self.assertIn("Pending approvals <span class='count'>3</span>", page)
        for p in pending:
            self.assertIn(f"#{p['id']} Decision on task {p['task']}", page)
            self.assertIn(srv._money(p["amount_minor"], "SIM"), page)
        self.assertNotIn("could not be read", page)

    def test_css_uses_the_design_tokens_exactly(self):
        """Verifies D-073: varje token i DESIGN.md finns med exakt samma värde i app.css, och mobilbredden finns."""
        design = (ROOT / "docs" / "dashboard" / "DESIGN.md").read_text(encoding="utf-8")
        css = (srv.WEB / "app.css").read_text(encoding="utf-8")
        tokens = re.findall(r"\| `(--[a-z-]+)`(?: / `(--[a-z-]+)`)? \| `(#[0-9A-F]{6})`(?: / `(#[0-9A-F]{6})`)? \|", design)
        self.assertGreaterEqual(len(tokens), 12)
        for name, name2, value, value2 in tokens:
            self.assertRegex(css, rf"{name}:\s*{value};")
            if name2:
                self.assertRegex(css, rf"{name2}:\s*{value2};")
        self.assertIn("@media (max-width: 767px)", css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("min-height: 44px", css)

    def test_fonts_are_local_with_ofl_licenses(self):
        """Verifies D-073: Cormorant Garamond och Inter ligger lokalt som woff2 med OFL-licens och serveras därifrån."""
        fonts = srv.WEB / "fonts"
        css = (srv.WEB / "app.css").read_text(encoding="utf-8")
        for url in re.findall(r'url\("([^"]+)"\)', css):
            self.assertTrue((srv.WEB / url).is_file(), url)
            self.assertEqual((srv.WEB / url).read_bytes()[:4], b"wOF2")
        for license_ in ("OFL-Inter.txt", "OFL-CormorantGaramond.txt"):
            self.assertIn("SIL Open Font License", (fonts / license_).read_text(encoding="utf-8"))
        self.assertNotRegex(css + (srv.WEB / "app.js").read_text(encoding="utf-8"), r"https?://")
        _, cookie = self.login()
        res, data = self.request("GET", "/static/fonts/inter-latin-400-normal.woff2", cookie=cookie)
        self.assertEqual((res.status, res.getheader("Content-Type"), data[:4]), (200, "font/woff2", b"wOF2"))


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
