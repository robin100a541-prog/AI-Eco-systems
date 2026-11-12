"""Kontrollerar att en driftsatt Command Center är stängd för den som inte är inloggad (D-094).

    py scripts/check_deploy.py https://aie-command-center.pages.dev

Utan sessionscookie ska varje sökväg ge 302 till `/login` (sidor och filer) eller 401 (API:t), och aldrig 200 med
data. Bara `/login` och dess stilmall får svara 200. Svarar sidan 503 "Not configured" saknas hemligheterna
FOUNDER_CODE_HASHES eller SESSION_SECRET: då är den stängd, men ingen kan logga in. Skriptet loggar inte in och
skickar inga hemligheter.

Avslutar med 0 när allt är stängt och inloggningssidan svarar, 3 när sidan svarar 503 (inte konfigurerad),
annars 1.
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request

PAGES = ("/", "/index.html", "/js/main.js", "/js/pages/finance.js", "/assets/css/app.css",
         "/assets/icons/lucide-sprite.svg", "/vendor/gsap/3.15.1/gsap.min.js")
API = ("/api/health", "/api/snapshot", "/api/me", "/api/github")
POSTS = ("/api/action", "/api/chat", "/logout")
OPEN = ("/login", "/login/login.css")
TIMEOUT = 15


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # följ aldrig omdirigeringen: vi vill se den


def fetch(url: str, method: str = "GET") -> tuple[int, str, str]:
    """Returnerar (status, Location, början av svaret). Följer inga omdirigeringar och skickar inga kakor."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method=method, data=b"{}" if method == "POST" else None,
                                     headers={"User-Agent": "aie-check-deploy", "Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=TIMEOUT) as res:
            return res.status, res.headers.get("Location", ""), res.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read(200).decode("utf-8", "replace") if exc.fp else ""
        return exc.code, (exc.headers.get("Location", "") if exc.headers else ""), body


def judge(kind: str, status: int, location: str, body: str = "") -> tuple[bool, str]:
    """kind: 'page' (ska ge 302 till /login), 'api' (401, eller 403 för POST utan session) eller 'open' (200)."""
    if status == 503 and "Not configured" in body:
        return False, "503 Not configured: hemligheterna saknas"
    if kind == "open":
        return (True, "200 öppen som den ska") if status == 200 else (False, f"{status}: inloggningssidan svarar inte")
    if 200 <= status < 300:
        return False, f"{status}: öppen utan inloggning"
    if kind == "page":
        if status == 302 and location in ("/login", "/login/"):
            return True, "302 till /login"
        return False, f"{status} till {location or 'ingenstans'}, inte 302 till /login"
    if status == 401:
        return True, "401 nekad"
    return False, f"{status}: oväntat svar"


def check(base: str, fetcher=None) -> list[tuple[str, bool, str]]:
    fetcher = fetcher or fetch
    base = base.rstrip("/")
    plan = [("GET", p, "page") for p in PAGES] + [("GET", p, "api") for p in API] + \
           [("POST", p, "api" if p.startswith("/api/") else "page") for p in POSTS] + [("GET", p, "open") for p in OPEN]
    results = []
    for method, path, kind in plan:
        try:
            ok, why = judge(kind, *fetcher(base + path, method))
        except Exception as exc:  # noqa: BLE001
            ok, why = False, f"gick inte att nå ({type(exc).__name__})"
        results.append((f"{method} {path}", ok, why))
    return results


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not argv[0].startswith("https://"):
        print("Användning: py scripts/check_deploy.py https://aie-command-center.pages.dev", file=sys.stderr)
        return 2
    results = check(argv[0])
    for name, ok, why in results:
        print(f"{'OK ' if ok else 'FEL'} {name}: {why}")
    failed = [r for r in results if not r[1]]
    if failed and all("Not configured" in why for _, _, why in failed) and len(failed) == len(results):
        print("\nSidan är stängd men inte konfigurerad: lägg in FOUNDER_CODE_HASHES och SESSION_SECRET i Cloudflare "
              "och publicera om (DEPLOY.md steg d).")
        return 3
    if failed:
        print(f"\n{len(failed)} av {len(results)} kontroller gick inte igenom.")
        return 1
    print(f"\nAlla {len(results)} kontroller gick igenom: allt utom inloggningssidan kräver inloggning.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
