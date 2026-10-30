"""Pilotens plattformsdata ur `config/pilot.toml` (D-056: inga plattformsnamn i koden)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[3] / "config" / "pilot.toml"


@dataclass(frozen=True, slots=True)
class PilotSettings:
    platform_key: str
    platform: str
    currency: str
    fee_percent: int
    fee_fixed_cents: int
    usd_sek: float
    csv: dict


def load(path: Path | str = DEFAULT) -> PilotSettings:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    p = data["platform"]
    return PilotSettings(p["slug"], p["name"], p["currency"], int(p["fee_percent"]), int(p["fee_fixed_cents"]),
                         float(data["usd_sek"]), {k: tuple(v) for k, v in data["csv"].items()})


SETTINGS = load()
