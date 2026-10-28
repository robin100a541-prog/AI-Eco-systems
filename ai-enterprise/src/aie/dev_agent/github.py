"""Öppnar utvecklaragentens PR och slår på automatisk merge (D-050).

Nätverket nås bara via en `Transport`, så testerna kan byta ut den. Token läses från miljön
(`BOT_TOKEN`) och står aldrig i felmeddelanden eller loggar (SR-10). Automatisk merge betyder att
GitHub mergear först när alla obligatoriska checkar är gröna, inklusive `protected-files`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

API = "https://api.github.com"
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]


class GitHubError(RuntimeError):
    pass


def urllib_transport(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, data=body, headers=dict(headers), method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubError(
            f"GitHub kunde inte nås: {getattr(exc, 'reason', exc)}"
        ) from None


class GitHub:
    def __init__(
        self, token: str, repo: str, transport: Transport = urllib_transport
    ) -> None:
        if not token:
            raise GitHubError("BOT_TOKEN saknas")
        if repo.count("/") != 1:
            raise GitHubError(f"ogiltigt repo {repo!r}")
        self._token = token
        self._repo = repo
        self._transport = transport

    def __repr__(self) -> str:  # aldrig token i en repr
        return f"GitHub(repo={self._repo!r})"

    def _call(self, method: str, path: str, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "aie-dev-agent",
        }
        status, raw = self._transport(
            method, API + path, headers, json.dumps(payload).encode()
        )
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        if status >= 300 or (path == "/graphql" and data.get("errors")):
            message = data.get("message") or data.get("errors") or raw[:200]
            raise GitHubError(
                f"GitHub svarade {status} på {path}: {str(message).replace(self._token, '***')}"
            )
        return data

    def open_pr(self, head: str, title: str, body: str, base: str = "main") -> dict:
        return self._call(
            "POST",
            f"/repos/{self._repo}/pulls",
            {"head": head, "base": base, "title": title, "body": body},
        )

    def enable_auto_merge(self, node_id: str) -> None:
        query = (
            "mutation($id: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $id, "
            "mergeMethod: MERGE}) { clientMutationId } }"
        )
        self._call("POST", "/graphql", {"query": query, "variables": {"id": node_id}})
