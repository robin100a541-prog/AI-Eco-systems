"""`python -m aie registry list|show|import|status` (PR 4, D-056).

    python -m aie registry list
    python -m aie registry show platform plattform-a
    python -m aie registry import --as yorgo                     # config/registry/*.toml
    python -m aie registry status platform plattform-a approved --as yorgo --note "villkoren lästa"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import runtime
from ..agents import AgentRegistry
from ..audit import AuditLog
from ..authorization import load_permissions
from ..config import ConfigError
from .registry import KINDS, Register, RegistryError
from .seed import import_dir


def registry(config_dir: Path, action: str, kind: str | None = None, key: str | None = None,
             status: str | None = None, founder: str | None = None, note: str = "") -> int:
    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            permissions = load_permissions(config_dir)
            register = Register(db, AgentRegistry(permissions, db), permissions, AuditLog(db),
                                frozenset(config.system.founders))
            try:
                if action == "list":
                    for k in KINDS:
                        for e in register.all(k):
                            print(f"{k:10} {e.key:20} {e.status:12} version {e.version}  {e.data.get('name', e.data.get('description', ''))}")
                    return 0
                if action == "show":
                    entry = register.get(kind, key)
                    if entry is None:
                        print(f"{kind} {key} finns inte.", file=sys.stderr)
                        return 1
                    print(json.dumps({"kind": entry.kind, "key": entry.key, "version": entry.version,
                                      "status": entry.status, "actor": entry.actor, "note": entry.note,
                                      "at": entry.at, "data": entry.data}, ensure_ascii=False, indent=2))
                    return 0
                if action == "import":
                    for line in import_dir(register, founder, config_dir):
                        print(line)
                    return 0
                entry = register.set_status(founder, kind, key, status, note)
                print(f"{kind} {key}: version {entry.version}, status {entry.status}")
                return 0
            except (RegistryError, ConfigError) as exc:
                print(f"FEL: {exc}", file=sys.stderr)
                return 1
    except runtime.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1
