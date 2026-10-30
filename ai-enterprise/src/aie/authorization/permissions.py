"""Rollernas mandat från `config/permissions.toml` (SR-02, D-017).

Filen har två delar:
- `[tools]`: katalogen med alla verktyg som finns. En roll kan bara få verktyg härifrån,
  så ett stavfel i ett mandat blir ett fel i stället för ett verktyg som tyst saknas.
- `[roles.<roll>]`: departement och en uttrycklig lista med tillåtna verktyg. Allt som
  inte står i listan är förbjudet (default deny).

Precis som i `config/loader.py` samlas alla fel innan `ConfigError` kastas.
Resultatet är oföränderligt, så att ingen kod (och ingen agent) kan utöka ett mandat
medan systemet kör (SR-03).
"""
from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..agents.hierarchy import (  # noqa: F401
    LEVEL_CEO,
    LEVEL_CONTROL,
    LEVEL_HEAD,
    LEVEL_WORKER,
    ROLE_LEVELS,
)
from ..config import ConfigError
from ..config.loader import is_secret_key

PERMISSIONS_FILE = "permissions.toml"
SUPPORTED_VERSION = 1
# Departementen i konstitutionen §10–19.
DEPARTMENTS = (
    "executive", "finance", "research", "development", "sales",
    "marketing", "operations", "risk", "compliance", "audit", "learning",
)
TOP_KEYS = ("config_version", "tools", "roles")
ROLE_KEYS = ("department", "description", "level", "tools")


# Styrverktyg som bara grundarna får använda (SR-04, §8 nivå 0). De kan stå i katalogen, så att
# försök kan loggas med rätt namn, men ingen roll kan få dem och motorn nekar dem alltid.
PROTECTED_PREFIX = "governance."

_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")  # t.ex. "report.write"
_ROLE_NAME = re.compile(r"[a-z][a-z0-9_]*")

Report = Callable[[str], None]  # tar emot ett felmeddelande


@dataclass(frozen=True, slots=True)
class Mandate:
    role: str
    department: str
    tools: frozenset[str]
    description: str = ""
    level: int = LEVEL_WORKER  # 1 CEO, 2 kontrollfunktion, 3 departementschef, 4 arbetsagent (§8)

    def allows(self, tool: str) -> bool:
        return tool in self.tools


@dataclass(frozen=True, slots=True)
class Permissions:
    tools: Mapping[str, str]  # verktyg → beskrivning
    roles: Mapping[str, Mandate]


def load_permissions(config_dir: Path | str = "config") -> Permissions:
    path = Path(config_dir) / PERMISSIONS_FILE
    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(f"{PERMISSIONS_FILE}: {message}")

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{PERMISSIONS_FILE}: filen saknas i {config_dir}"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError([f"{PERMISSIONS_FILE}: kan inte tolkas som TOML: {exc}"]) from None

    _reject_secrets(data, "", error)
    for key in data:
        if key not in TOP_KEYS and not is_secret_key(key):
            error(f"okänd nyckel {key!r} (tillåtna: {', '.join(TOP_KEYS)})")
    if data.get("config_version") != SUPPORTED_VERSION or isinstance(data.get("config_version"), bool):
        error(f"config_version = {data.get('config_version')!r} stöds inte (förväntat {SUPPORTED_VERSION})")

    tools = _parse_tools(data.get("tools"), error)
    roles = _parse_roles(data.get("roles"), tools, error)

    if errors:
        raise ConfigError(errors)
    return Permissions(tools=MappingProxyType(tools), roles=MappingProxyType(roles))


def _parse_tools(raw: Any, error: Report) -> dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        error("[tools] saknas eller är tom; varje verktyg måste finnas i katalogen")
        return {}
    tools: dict[str, str] = {}
    for name, description in raw.items():
        if is_secret_key(name):
            continue  # redan rapporterad
        if not _TOOL_NAME.fullmatch(name):
            error(f"verktygsnamnet {name!r} är ogiltigt (t.ex. 'report.write': gemener och punkt)")
        elif not isinstance(description, str) or not description.strip():
            error(f"verktyget {name!r} behöver en beskrivning (text)")
        else:
            tools[name] = description
    return tools


def _parse_roles(raw: Any, tools: Mapping[str, str], error: Report) -> dict[str, Mandate]:
    if not isinstance(raw, dict) or not raw:
        error("[roles] saknas eller är tom")
        return {}
    roles: dict[str, Mandate] = {}
    for role, spec in raw.items():
        where = f"roles.{role}"
        if not _ROLE_NAME.fullmatch(role):
            error(f"rollnamnet {role!r} är ogiltigt (gemener, siffror och _)")
            continue
        if not isinstance(spec, dict):
            error(f"{where} måste vara en tabell")
            continue
        ok = True
        for key in spec:
            if key not in ROLE_KEYS and not is_secret_key(key):
                error(f"{where}: okänd nyckel {key!r} (tillåtna: {', '.join(ROLE_KEYS)})")
                ok = False
        department = spec.get("department")
        if department not in DEPARTMENTS:
            error(f"{where}: department = {department!r} är okänt (tillåtna: {', '.join(DEPARTMENTS)})")
            ok = False
        listed = spec.get("tools")
        if not isinstance(listed, list) or not all(isinstance(t, str) for t in listed):
            error(f"{where}: tools måste vara en lista med verktygsnamn (tom lista = får ingenting)")
            ok = False
            listed = []
        for tool in listed:
            if tool not in tools:
                error(f"{where}: verktyget {tool!r} finns inte i [tools]")
                ok = False
            elif tool.startswith(PROTECTED_PREFIX):
                error(f"{where}: {tool!r} är ett styrverktyg som bara grundarna får använda (SR-04)")
                ok = False
        level = spec.get("level")
        if not isinstance(level, int) or isinstance(level, bool) or level not in ROLE_LEVELS:
            error(f"{where}: level = {level!r} måste vara 1 (CEO), 2 (kontrollfunktion), "
                  "3 (departementschef) eller 4 (arbetsagent) (§8, D-020)")
            ok = False
        if len(set(listed)) != len(listed):
            error(f"{where}: samma verktyg står flera gånger")
            ok = False
        description = spec.get("description", "")
        if not isinstance(description, str):
            error(f"{where}: description måste vara text")
            ok = False
        if ok:
            roles[role] = Mandate(role, department, frozenset(listed), description, level)
    return roles


def _reject_secrets(data: Any, prefix: str, error: Report) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            dotted = f"{prefix}{key}"
            if is_secret_key(key):
                error(f"{dotted} ser ut som en hemlighet; hemligheter läses från miljövariabler (SR-10)")
            _reject_secrets(value, f"{dotted}.", error)
    elif isinstance(data, list):
        for item in data:
            _reject_secrets(item, prefix, error)
