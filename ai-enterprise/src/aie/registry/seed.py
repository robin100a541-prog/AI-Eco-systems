"""Läser plattformar och initiativ från `config/registry/*.toml` in i registret (PR 4, D-056).

TOML saknar null, så ett okänt belopp skrivs `"null"` och blir `None` här. En post som redan finns med
samma innehåll och status hoppas över, så att importen kan köras flera gånger. En ändrad post blir en ny
version. Bara en grundare importerar.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from ..config import ConfigError
from .registry import Register, RegistryError

REGISTRY_DIR = "registry"


def _nulls(value):
    if value == "null":
        return None
    if isinstance(value, dict):
        return {k: _nulls(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_nulls(v) for v in value]
    return value


def read_file(path: Path | str) -> dict[str, list[dict]]:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{path}: filen saknas"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError([f"{path}: kan inte tolkas som TOML: {exc}"]) from None
    if data.get("config_version") != 1:
        raise ConfigError([f"{path}: config_version ska vara 1"])
    return {"platform": [_nulls(p) for p in data.get("platforms", [])],
            "initiative": [_nulls(i) for i in data.get("initiatives", [])]}


def import_file(register: Register, founder: str, path: Path | str) -> list[str]:
    """Importerar en fil. Returnerar vad som hände per post."""
    out = []
    for kind, items in read_file(path).items():
        for item in items:
            item = dict(item)
            key, status = item.pop("key", None), item.pop("status", "investigated")
            if not key:
                raise ConfigError([f"{path}: en {kind} saknar key"])
            current = register.get(kind, key)
            if current is not None and current.data == item and current.status == status:
                out.append(f"{kind} {key}: oförändrad (version {current.version})")
                continue
            try:
                entry = register.record(founder, kind, key, status, item, f"import från {Path(path).name}")
            except RegistryError as exc:
                raise ConfigError([f"{path}: {kind} {key}: {exc}"]) from None
            out.append(f"{kind} {key}: version {entry.version} ({entry.status})")
    return out


def import_dir(register: Register, founder: str, config_dir: Path | str) -> list[str]:
    folder = Path(config_dir) / REGISTRY_DIR
    out = []
    for path in sorted(folder.glob("*.toml")) if folder.is_dir() else ():
        out += import_file(register, founder, path)
    return out
