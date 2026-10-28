"""`python -m aie research fetch|history` (PR 5, D-057).

    python -m aie research fetch https://www.skatteverket.se/ --agent res-1
    python -m aie research history

En agent med `research.search` hämtar en känd sida. Resultatet sparas och skrivs ut inramat som
opålitlig data (SR-06). Inget sök-API används, och bara värdarna i `config/research.toml` tillåts.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import runtime
from ..agents import AgentRegistry
from ..audit import AuditLog
from ..authorization import AuthorizationEngine, PermissionDenied, load_permissions
from ..config import ConfigError
from .web import WebError, WebReader, load_limits


def research(config_dir: Path, action: str, url: str | None = None, agent: str | None = None) -> int:
    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            try:
                limits = load_limits(config_dir)
            except ConfigError as exc:
                raise runtime.StartupError(f"FEL: {exc}") from exc
            permissions = load_permissions(config_dir)
            audit = AuditLog(db)
            engine = AuthorizationEngine(permissions, AgentRegistry(permissions, db), config.system.environment, audit)
            reader = WebReader(db, engine, audit, limits)
            if action == "history":
                for row in reader.history():
                    print(f"#{row['id']} {row['at']} {row['agent']} {row['outcome']:8} {row['url']} ({row['reason']})")
                return 0
            try:
                page = reader.fetch(agent, url)
            except (WebError, PermissionDenied) as exc:
                print(f"FEL: {exc}", file=sys.stderr)
                return 1
            print(page.content.render())
            if page.signals:
                print(f"Varning: texten innehåller försök att styra agenter: {', '.join(page.signals)} (SR-06)")
            print(f"Sparad som hämtning #{page.fetch_id}{' (avkortad)' if page.truncated else ''}.")
            return 0
    except runtime.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1
