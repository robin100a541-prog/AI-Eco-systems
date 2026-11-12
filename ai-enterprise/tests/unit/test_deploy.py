"""Command Center Del 6: driftsättningskontrollen, säkerhetsrubrikerna och det som publiceras."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
CC = ROOT / "command-center"


def load_script():
    spec = importlib.util.spec_from_file_location("check_deploy", ROOT / "scripts" / "check_deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCheckDeploy(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    @staticmethod
    def closed(url, method):
        path = "/" + url.split("/", 3)[3]
        if path in ("/login", "/login/login.css"):
            return 200, "", "<html>"
        if path.startswith("/api/"):
            return 401, "", '{"error":"unauthorized"}'
        return 302, "/login", ""

    def test_without_a_cookie_everything_is_302_to_login_or_401_and_never_200(self):
        """Verifies FR-28, D-094: utan sessionscookie ger varje sida och fil 302 till /login och API:t 401; bara
        inloggningssidan svarar 200. Ett 200-svar med data, eller en omdirigering någon annanstans, är fel."""
        results = self.script.check("https://x.pages.dev/", self.closed)
        self.assertTrue(all(ok for _, ok, _ in results), [r for r in results if not r[1]])
        names = [name for name, _, _ in results]
        for needed in ("GET /", "GET /js/main.js", "GET /assets/css/app.css", "GET /api/health", "GET /api/snapshot",
                       "POST /api/action", "POST /api/chat", "POST /logout", "GET /login"):
            self.assertIn(needed, names)

        def health_open(url, method):
            return (200, "", '{"status":"ok"}') if url.endswith("/api/health") else self.closed(url, method)

        results = dict((name, ok) for name, ok, _ in self.script.check("https://x.pages.dev", health_open))
        self.assertFalse(results["GET /api/health"])
        self.assertTrue(results["GET /"])
        self.assertFalse(self.script.judge("page", 200, "", "<html>")[0])
        self.assertFalse(self.script.judge("page", 302, "https://evil.example/login")[0])
        self.assertFalse(self.script.judge("api", 302, "/login")[0])
        self.assertFalse(self.script.judge("open", 404, "")[0])

    def test_missing_secrets_show_as_503_not_configured(self):
        """Verifies D-094: saknas hemligheterna svarar allt 503 "Not configured"; skriptet säger det och avslutar med 3."""
        self.assertEqual(self.script.judge("page", 503, "", "Not configured"), (False, "503 Not configured: hemligheterna saknas"))
        self.script.fetch, real = (lambda url, method="GET": (503, "", "Not configured")), self.script.fetch
        self.addCleanup(setattr, self.script, "fetch", real)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.script.main(["https://x.pages.dev"]), 3)
        self.assertIn("inte konfigurerad", out.getvalue())

    def test_exit_codes_and_unreachable_site(self):
        """Verifies D-094: skriptet avslutar med 1 när något är öppet eller inte går att nå, och kräver https."""
        def down(url, method):
            raise OSError("no route")

        self.assertTrue(all(not ok for _, ok, _ in self.script.check("https://x.pages.dev", down)))
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.script.main(["http://x.pages.dev"]), 2)
            self.assertEqual(self.script.main([]), 2)


class TestPublished(unittest.TestCase):
    def test_security_headers(self):
        """Verifies FR-28, D-087: _headers sätter strikt CSP utan externa källor och utan unsafe-inline,
        X-Frame-Options DENY, Referrer-Policy och no-store på API-svar."""
        headers = (CC / "public" / "_headers").read_text(encoding="utf-8")
        csp = re.search(r"Content-Security-Policy: (.+)", headers).group(1)
        for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "connect-src 'self'",
                          "frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'"):
            self.assertIn(directive, csp)
        self.assertNotIn("unsafe", csp)
        self.assertNotRegex(csp, r"https?:|\*")
        self.assertIn("X-Frame-Options: DENY", headers)
        self.assertIn("Referrer-Policy: no-referrer", headers)
        self.assertRegex(headers, r"/api/\*\n\s+Cache-Control: no-store")
        middleware = (CC / "functions" / "_middleware.js").read_text(encoding="utf-8")
        self.assertIn('out.headers.set("Cache-Control", "no-store")', middleware)

    def test_only_the_public_folder_is_published_and_it_holds_no_secrets(self):
        """Verifies SR-10, D-085: det som publiceras ligger i command-center/public; tester, hjälpkod och funktioner
        ligger utanför, och ingen hemlighet eller token står i webbläsarens filer."""
        public = {p.name for p in (CC / "public").iterdir()}
        self.assertEqual(public, {"index.html", "_headers", "assets", "js", "vendor", "login"})
        self.assertEqual({p.name for p in (CC / "public" / "login").iterdir()}, {"login.css"})  # det enda som är öppet
        self.assertEqual({p.name for p in CC.iterdir()}, {"public", "functions", "lib", "tests"})
        self.assertEqual({p.name for p in (CC / "functions").iterdir()}, {"_middleware.js", "api", "login.js", "logout.js"})
        names = ("GITHUB_READ_TOKEN", "GITHUB_DISPATCH_TOKEN", "GROQ_API_KEY", "CLOUDFLARE_API_TOKEN", "SESSION_SECRET",
                 "FOUNDER_CODE_HASHES", "NTFY_TOPIC", "GMAIL_APP_PASSWORD", "STATE_KEY")
        for f in [*(CC / "public" / "js").rglob("*.js"), CC / "public" / "index.html"]:
            text = f.read_text(encoding="utf-8")
            for name in names:
                self.assertNotIn(name, text, f.name)
            self.assertNotRegex(text, r"(ghp_|github_pat_|gsk_)[A-Za-z0-9]{8}", f.name)

    def test_env_example_lists_only_used_variables_and_env_is_ignored(self):
        """Verifies SR-10: .env.example har bara variabler som koden eller funktionerna faktiskt läser, utan värden,
        och .env ligger i .gitignore."""
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        names = re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=(.*)$", example, re.M)
        self.assertGreaterEqual(len(names), 12)
        code = "".join(p.read_text(encoding="utf-8", errors="replace") for p in [
            *(ROOT / "src").rglob("*.py"), *(CC / "functions").rglob("*.js"), *(CC / "lib").rglob("*.js"),
            *(REPO / ".github" / "workflows").glob("*.yml"), ROOT / "scripts" / "state.sh"])
        for name, value in names:
            self.assertEqual(value.strip(), "", name)
            self.assertIn(name.removesuffix("_YORGO").removesuffix("_ROBIN"), code, name)
        for gone in ("ANTHROPIC_API_KEY", "ACCESS_TEAM_DOMAIN", "ACCESS_AUD", "ALLOWED_EMAILS"):
            self.assertNotIn(gone, example)
        all_text = code + "".join(p.read_text(encoding="utf-8", errors="replace") for p in (CC / "public" / "js").rglob("*.js"))
        for gone in ("ACCESS_TEAM_DOMAIN", "ACCESS_AUD", "ALLOWED_EMAILS", "Cf-Access-Jwt-Assertion", "cloudflareaccess"):
            self.assertNotIn(gone, all_text, gone)  # D-094: Cloudflare Access används inte
        self.assertRegex((ROOT / ".gitignore").read_text(encoding="utf-8"), r"(?m)^\.env$")

    def test_ekobyn_and_duplicates_are_gone_and_root_pages_remain(self):
        """Verifies D-077, D-092: Ekobyn och Pinterest-dubbletterna är borttagna, rotens sidor finns kvar, och inget
        data ligger kvar i repot."""
        for gone in ("docs/dashboard/index.html", "docs/dashboard/world.js", "docs/dashboard/world.css",
                     "docs/dashboard/status.json", "docs/dashboard/app.html", "docs/dashboard/privacy.html",
                     "tests/dashboard_world.cjs"):
            self.assertFalse((ROOT / gone).exists(), gone)
        if (REPO / ".github").is_dir():  # hela repot (inte bara ai-enterprise utcheckat)
            self.assertFalse((REPO / ".github" / "workflows" / "dashboard-world.yml").exists())
            for kept in ("index.html", "app.html", "privacy.html"):
                self.assertTrue((REPO / kept).is_file(), kept)
                self.assertFalse((REPO / "docs" / kept).exists(), kept)
        for kept in ("docs/dashboard/DASHBOARD_PLAN.md", "docs/dashboard/GAP_ANALYSIS.md", "docs/dashboard/DESIGN.md",
                     "docs/command-center/DATA.md", "docs/command-center/DEPLOY.md"):
            self.assertTrue((ROOT / kept).is_file(), kept)


if __name__ == "__main__":
    unittest.main()
