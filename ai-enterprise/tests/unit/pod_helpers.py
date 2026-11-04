"""Hjälp för testerna av print-on-demand (arbetsorder 04). Inga nätverksanrop: en `FakeTransport`
svarar i stället för API:erna och sparar varje anrop.

`pod_config()` är en kopia av testkonfigurationen där de nya verktygen finns i `permissions.toml`,
eftersom repots fil är skyddad och får verktygen först när en grundare har godkänt den PR:en.
"""
import json
import re
import shutil
import tempfile
from pathlib import Path

from aie.pod.http import Response

from .fixture_config import TEST_CONFIG

POD_TOOLS = {
    "printify.read": "läsa Printifys katalog och butik",
    "printify.draft": "skapa en opublicerad produkt i Printify",
    "etsy.read": "läsa Etsys offentliga listningar och recensioner",
    "pinterest.trends": "läsa Pinterests trender",
    "pinterest.pin": "skapa en pin",
    "instagram.publish": "publicera ett inlägg på Instagram",
}
GRANTS = {"researcher": ["printify.read", "etsy.read", "pinterest.trends"],
          "scout": ["printify.read", "etsy.read", "pinterest.trends"],
          "research_lead": ["printify.read", "printify.draft", "pinterest.pin", "instagram.publish"]}


def pod_config(tmp: Path, **pod_overrides) -> Path:
    config = Path(tmp) / "config"
    shutil.copytree(TEST_CONFIG, config)
    perms = config / "permissions.toml"
    text = perms.read_text(encoding="utf-8")
    text = text.replace("[tools]\n", "[tools]\n" + "".join(f'"{k}" = "{v}"\n' for k, v in POD_TOOLS.items()), 1)
    for role, tools in GRANTS.items():
        pattern = rf'(\[roles\.{role}\][^\[]*?tools = \[)'
        text = re.sub(pattern, lambda m: m.group(1) + "".join(f'"{t}", ' for t in tools), text, count=1, flags=re.S)
    perms.write_text(text, encoding="utf-8")
    pod = (config / "pod.toml").read_text(encoding="utf-8")
    for key, value in pod_overrides.items():
        pod = re.sub(rf"^{key} = .*$", f"{key} = {value}", pod, count=1, flags=re.M)
    (config / "pod.toml").write_text(pod, encoding="utf-8")
    return config


class FakeTransport:
    """`routes`: {(metod, sökväg utan frågesträng): [svar, ...]}. Ett svar är (status, data, rubriker)."""

    def __init__(self, routes=None):
        self.routes = {k: list(v) for k, v in (routes or {}).items()}
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        path = re.sub(r"^https://[^/]+", "", url).split("?", 1)[0]
        self.calls.append({"method": method, "url": url, "path": path, "headers": dict(headers),
                           "body": json.loads(body) if body else None, "timeout": timeout})
        queue = self.routes.get((method, path))
        if not queue:
            return Response(404, {}, b'{"error": "not found in fake"}')
        status, data, headers_ = queue.pop(0) if len(queue) > 1 else queue[0]
        return Response(status, headers_ or {}, json.dumps(data).encode("utf-8") if data is not None else b"")


def tmpdir(case) -> Path:
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    return Path(tmp.name)
