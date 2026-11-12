"""Kontrollerar att en driftsatt Command Center är stängd för den som inte är inloggad (Del 6, D-086).

    py scripts/check_deploy.py https://<projekt>.pages.dev

Utan inloggning ska varje adress ge en omdirigering till Cloudflare Access (`*.cloudflareaccess.com`), och aldrig
200. Det gäller sidan, skripten, stilmallen och hela API:t, också `/api/health`. Skriptet loggar inte in och skickar
inga hemligheter. Avslutar med 0 när allt är stängt, annars 1.
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request

PATHS = ("/", "/index.html", "/js/main.js", "/assets/css/app.css", "/api/health", "/api/snapshot", "/api/me",
         "/api/github")
POST_PATHS = ("/api/action", "/api/chat")
ACCESS_SUFFIX = ".cloudflareaccess.com"
TIMEOUT = 15


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # följ aldrig omdirigeringen: vi vill se den


def fetch(url: str, method: str = "GET") -> tuple[int, str]:
    """Returnerar (status, Location). Följer inga omdirigeringar och skickar inga kakor."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method=method, data=b"{}" if method == "POST" else None,
                                     headers={"User-Agent": "aie-check-deploy", "Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=TIMEOUT) as res:
            return res.status, res.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "") if exc.headers else ""


def judge(status: int, location: str) -> tuple[bool, str]:
    """En adress är stängd om den omdirigerar till Access, eller nekar med 401 eller 403. 200 är alltid fel."""
    host = urllib.parse.urlsplit(location).hostname or ""
    if status in (301, 302, 303, 307, 308):
        if host.endswith(ACCESS_SUFFIX):
            return True, f"{status} till Cloudflare Access"
        return False, f"{status} till {host or 'okänd adress'}, inte till Cloudflare Access"
    if status in (401, 403):
        return True, f"{status} nekad"
    if 200 <= status < 300:
        return False, f"{status}: öppen utan inloggning"
    return False, f"{status}: oväntat svar"


def check(base: str, fetcher=fetch) -> list[tuple[str, bool, str]]:
    base = base.rstrip("/")
    results = []
    for method, paths in (("GET", PATHS), ("POST", POST_PATHS)):
        for path in paths:
            try:
                ok, why = judge(*fetcher(base + path, method))
            except Exception as exc:  # noqa: BLE001
                ok, why = False, f"gick inte att nå ({type(exc).__name__})"
            results.append((f"{method} {path}", ok, why))
    return results


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not argv[0].startswith("https://"):
        print("Användning: py scripts/check_deploy.py https://<projekt>.pages.dev", file=sys.stderr)
        return 2
    results = check(argv[0])
    for name, ok, why in results:
        print(f"{'OK ' if ok else 'FEL'} {name}: {why}")
    failed = [r for r in results if not r[1]]
    if failed:
        print(f"\n{len(failed)} av {len(results)} adresser är inte stängda. Kontrollera Access-applikationen (DEPLOY.md steg 3).")
        return 1
    print(f"\nAlla {len(results)} adresser kräver inloggning via Cloudflare Access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
