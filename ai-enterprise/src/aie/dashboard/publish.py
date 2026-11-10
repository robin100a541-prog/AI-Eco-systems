"""`py -m aie publish`: laddar upp snapshoten (och rapporter) till Cloudflare KV (Del 1, D-085).

- Hemligheter läses bara ur miljön: `CLOUDFLARE_API_TOKEN` (bara rätt till KV), `CLOUDFLARE_ACCOUNT_ID` och
  `KV_NAMESPACE_ID`. De skrivs aldrig ut eller loggas.
- Saknas de hoppas uppladdningen över med en varning. Det är inget fel.
- Misslyckas uppladdningen loggas det, snapshoten sparas lokalt i `data/publish-pending/`, och nästa körning försöker
  igen. Kommandot avslutar alltid med 0 vid nätverksfel: agenternas arbete får aldrig stoppas eller bli långsammare
  för att rapporteringen fallerar (krav i Del 1).
- KV-nycklar: `snapshot:latest`, `snapshot:<YYYY-MM-DD>` (sparas 35 dagar) och `report:<filnamn>` (35 dagar).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..monitoring import get_logger

log = get_logger("publish")
API = "https://api.cloudflare.com/client/v4/accounts/{account}/storage/kv/namespaces/{namespace}/values/{key}"
HISTORY_TTL = 35 * 24 * 3600
TIMEOUT = 15
ENV = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "KV_NAMESPACE_ID")


class KV:
    """Minsta möjliga klient för Cloudflare KV:s REST-API (bara standardbiblioteket)."""

    def __init__(self, token: str, account: str, namespace: str, opener=urllib.request.urlopen) -> None:
        self._token, self._account, self._namespace, self._open = token, account, namespace, opener

    @classmethod
    def from_env(cls, environ=os.environ) -> "KV | None":
        values = [environ.get(k, "").strip() for k in ENV]
        return cls(*values) if all(values) else None

    def _url(self, key: str, ttl: int | None = None) -> str:
        url = API.format(account=self._account, namespace=self._namespace, key=urllib.parse.quote(key, safe=""))
        return url + (f"?expiration_ttl={ttl}" if ttl else "")

    def put(self, key: str, body: bytes, ttl: int | None = None, content_type: str = "application/octet-stream") -> None:
        request = urllib.request.Request(self._url(key, ttl), data=body, method="PUT", headers={
            "Authorization": f"Bearer {self._token}", "Content-Type": content_type})
        with self._open(request, timeout=TIMEOUT) as res:
            if res.status >= 300:
                raise OSError(f"KV svarade {res.status}")

    def keys(self, prefix: str) -> list[str]:
        """Nycklarna med prefixet, sorterade (högst 1000, vilket räcker för kön)."""
        url = self._url("x").rsplit("/values/", 1)[0] + "/keys?prefix=" + urllib.parse.quote(prefix, safe="")
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._token}"})
        with self._open(request, timeout=TIMEOUT) as res:
            body = json.loads(res.read() or b"{}")
        return sorted(item["name"] for item in body.get("result") or [])

    def delete(self, key: str) -> None:
        request = urllib.request.Request(self._url(key), method="DELETE",
                                         headers={"Authorization": f"Bearer {self._token}"})
        with self._open(request, timeout=TIMEOUT):
            pass

    def get(self, key: str) -> bytes | None:
        request = urllib.request.Request(self._url(key), headers={"Authorization": f"Bearer {self._token}"})
        try:
            with self._open(request, timeout=TIMEOUT) as res:
                return res.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise


def _put_retry(kv: KV, key: str, body: bytes, ttl: int | None, content_type: str, tries: int = 3) -> None:
    for attempt in range(tries):
        try:
            return kv.put(key, body, ttl, content_type)
        except (OSError, urllib.error.URLError) as exc:
            if attempt == tries - 1:
                raise
            log.warning("KV-uppladdning av %s misslyckades (%s); försöker igen", key, type(exc).__name__)
            time.sleep(2 * (attempt + 1))


def publish_snapshot(snapshot: dict, kv: KV | None, pending_dir: Path, reports: list[Path] = ()) -> str:
    """Laddar upp snapshoten. Returnerar 'published', 'skipped' (inga hemligheter) eller 'failed'. Kastar aldrig."""
    body = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pending_dir = Path(pending_dir)
    if kv is None:
        log.warning("publish hoppas över: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID eller KV_NAMESPACE_ID saknas")
        return "skipped"
    try:
        _put_retry(kv, "snapshot:latest", body, None, "application/json")
        _put_retry(kv, f"snapshot:{snapshot['generated_at'][:10]}", body, HISTORY_TTL, "application/json")
        for report in reports:
            _put_retry(kv, f"report:{Path(report).name}", Path(report).read_bytes(), HISTORY_TTL, "text/markdown")
    except Exception as exc:  # noqa: BLE001 — rapporteringen får aldrig stoppa agenterna
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "snapshot.json").write_bytes(body)
        log.error("publish misslyckades (%s); snapshoten sparad i %s och skickas nästa gång", type(exc).__name__,
                  pending_dir)
        return "failed"
    (pending_dir / "snapshot.json").unlink(missing_ok=True)
    log.info("snapshot publicerad (%d byte)", len(body))
    return "published"


def publish(config_dir: Path, out: Path | None = None, reports_dir: Path | None = None,
            pilot_root: Path | None = Path("data-pilot")) -> int:
    """CLI: bygger snapshoten ur databasen och laddar upp den. Avslutar med 0 även när uppladdningen misslyckas."""
    from .. import runtime
    from ..simulation.market import SimClock
    from ..simulation.run import stored_run
    from ..system import build_system
    from .snapshot import build_snapshot

    try:
        config = runtime._load(config_dir, console=False)
    except runtime.StartupError as exc:
        return runtime._fail(exc)
    with runtime._open(config) as db:
        run = stored_run(db)
        system = build_system(config, db, config_dir, clock=SimClock(run["start_date"]) if run else None)
        real = None
        if pilot_root is not None and (Path(pilot_root) / "data" / "prod.db").exists()                 and not (Path(pilot_root) / "config").is_dir():
            from ..pilot.live import pilot_config  # pilotens config härleds ur repots config (D-056)

            pilot_config(Path(config_dir), Path(pilot_root))
        if pilot_root is not None and (Path(pilot_root) / "config").is_dir():
            pconfig = runtime._load(Path(pilot_root) / "config", console=False)
            with runtime._open(pconfig) as pdb:
                real = build_system(pconfig, pdb, Path(pilot_root) / "config")
                snapshot = build_snapshot(system, config, config_dir, real_system=real,
                                          commit=os.environ.get("GITHUB_SHA"))
        else:
            snapshot = build_snapshot(system, config, config_dir, commit=os.environ.get("GITHUB_SHA"))
    if out is not None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    reports = sorted(Path(reports_dir).glob("*.md"))[-3:] if reports_dir and Path(reports_dir).is_dir() else []
    result = publish_snapshot(snapshot, KV.from_env(), Path(config.system.data_dir) / "publish-pending", reports)
    print(f"Snapshot {snapshot['generated_at']}: {result} ({len(snapshot['agents']['items'])} agenter, "
          f"revisionskedja {'OK' if snapshot['audit_chain']['ok'] else 'TRASIG'})")
    if result == "failed":
        print("Varning: uppladdningen misslyckades. Agenterna påverkas inte; nästa körning försöker igen.",
              file=sys.stderr)
    return 0


STATE_NAMES = ("company", "pilot", "scout")


def state(action: str, name: str, file: Path, kv: "KV | None" = None) -> int:
    """`aie state put|get`: flyttar en redan krypterad databaskopia (openssl i workflowen) till eller från KV.

    Filen krypteras innan den når hit; klartext lämnar aldrig runnern. Avslutar med 0 när KV inte är
    konfigurerat (put: inget sparas; get: inget hämtas), så att körningen aldrig stoppas av det.
    """
    if name not in STATE_NAMES:
        print(f"FEL: okänt namn {name!r}; välj {', '.join(STATE_NAMES)}", file=sys.stderr)
        return 1
    kv = kv or KV.from_env()
    if kv is None:
        print(f"state {action} {name}: KV är inte konfigurerat; hoppar över")
        return 0
    key = f"state:{name}"
    try:
        if action == "put":
            data = Path(file).read_bytes()
            _put_retry(kv, key, data, None, "application/octet-stream")
            print(f"state put {name}: {len(data)} byte sparade i KV")
            return 0
        data = kv.get(key)
        if data is None:
            print(f"state get {name}: ingen kopia i KV")
            return 3
        Path(file).parent.mkdir(parents=True, exist_ok=True)
        Path(file).write_bytes(data)
        print(f"state get {name}: {len(data)} byte hämtade från KV")
        return 0
    except Exception as exc:  # noqa: BLE001 — tillståndskopian får aldrig stoppa agenterna
        log.error("state %s %s misslyckades: %s", action, name, type(exc).__name__)
        print(f"Varning: state {action} {name} misslyckades ({type(exc).__name__})", file=sys.stderr)
        return 0 if action == "put" else 4
