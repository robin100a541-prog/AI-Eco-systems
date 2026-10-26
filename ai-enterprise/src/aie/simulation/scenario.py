"""Scenarier för affärssimuleringen (Fas 6b-1, FR-20, §54, D-042).

Ett scenario är en TOML-fil i `config/scenarios/`. Allt i den är simulerat, och belopp är heltal i
minsta enhet i `SIM` (D-006). Sannolikheter anges i baspunkter (10 000 = 100 %).

```toml
config_version = 1
name = "normal"
description = "..."
seed = "normal-1"          # samma seed ger samma körning
days = 30
start_date = "2027-01-01"

[[initiatives]]
key = "etsy-mallar"        # ledgerns affärsinitiativ
department = "research"
track = "partnership"      # skattespår (D-010, simulerat); isk/self_employment/hobby kräver owner
price = 4_900              # pris per order
unit_cost = 0              # kostnad per order (till exempel tryck); 0 för digitala varor
fee_fixed = 20             # plattformsavgift per order
fee_bp = 650               # plattformsavgift i baspunkter av priset
visitors = 40              # möjliga köpare per dag
conversion_bp = 500        # sannolikhet att en besökare köper
refund_bp = 200            # sannolikhet att en order återbetalas
listed_from = 1            # första dagen initiativet säljer

[[events]]
day = 10
kind = "demand_shock"      # se EVENT_KINDS
initiative = "etsy-mallar"
factor_bp = 0              # 0 = ingen efterfrågan, 10 000 = oförändrad
until = 15                 # sista dagen; utan until gäller händelsen en dag
note = "..."
```
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..config import ConfigError
from ..tax import TRACKS

SCENARIO_DIR = "scenarios"
MARKET_EVENTS = frozenset({"demand_shock", "platform_outage", "cost_spike"})
ACTOR_EVENTS = frozenset({"security_incident", "kill_switch"})  # utförs av en aktiv agent i en roll
AGENT_EVENTS = frozenset({"conflicting_assessment", "overspend_attempt"})  # tolkas av arbetscykeln (6b-2)
EVENT_KINDS = MARKET_EVENTS | ACTOR_EVENTS | AGENT_EVENTS
_INITIATIVE_INTS = ("price", "unit_cost", "fee_fixed", "fee_bp", "visitors", "conversion_bp", "refund_bp",
                    "listed_from")
_BP = ("fee_bp", "conversion_bp", "refund_bp")


@dataclass(frozen=True, slots=True)
class Initiative:
    key: str
    department: str
    track: str
    price: int
    unit_cost: int
    fee_fixed: int
    fee_bp: int
    visitors: int
    conversion_bp: int
    refund_bp: int
    listed_from: int = 1
    owner: str | None = None


@dataclass(frozen=True, slots=True)
class Event:
    day: int
    kind: str
    initiative: str | None = None
    factor_bp: int | None = None
    until: int | None = None
    role: str | None = None  # för ACTOR_EVENTS: vilken roll som agerar
    note: str = ""

    def active_on(self, day: int) -> bool:
        return self.day <= day <= (self.until or self.day)


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    description: str
    seed: str
    days: int
    start_date: str
    initiatives: tuple[Initiative, ...]
    events: tuple[Event, ...] = field(default=())

    def initiative(self, key: str) -> Initiative:
        return next(i for i in self.initiatives if i.key == key)


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def scenario_path(config_dir: Path | str, name: str) -> Path:
    return Path(config_dir) / SCENARIO_DIR / f"{name}.toml"


def available(config_dir: Path | str) -> tuple[str, ...]:
    folder = Path(config_dir) / SCENARIO_DIR
    return tuple(sorted(p.stem for p in folder.glob("*.toml"))) if folder.is_dir() else ()


def load_scenario(config_dir: Path | str, name: str, departments, founders) -> Scenario:
    path = scenario_path(config_dir, name)
    where = f"{SCENARIO_DIR}/{name}.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{where}: scenariot finns inte (finns: {', '.join(available(config_dir)) or 'inga'})"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError([f"{where}: kan inte tolkas som TOML: {exc}"]) from None
    return parse_scenario(data, where, departments, founders)


def parse_scenario(data: dict, where: str, departments, founders) -> Scenario:
    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(f"{where}: {message}")

    for key in data:
        if key not in ("config_version", "name", "description", "seed", "days", "start_date", "initiatives", "events"):
            error(f"okänd nyckel {key!r}")
    if data.get("config_version") != 1 or isinstance(data.get("config_version"), bool):
        error("config_version ska vara 1")
    for key in ("name", "description", "seed"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            error(f"{key} ska vara en text som inte är tom")
    days = data.get("days")
    if not _int(days) or not 1 <= days <= 3_650:
        error("days ska vara ett heltal 1–3 650")
        days = 0
    try:
        date.fromisoformat(data.get("start_date", ""))
    except (TypeError, ValueError):
        error("start_date ska vara ett datum, ÅÅÅÅ-MM-DD")

    initiatives: list[Initiative] = []
    raw = data.get("initiatives")
    if not isinstance(raw, list) or not raw:
        error("minst ett [[initiatives]] krävs")
        raw = []
    for n, item in enumerate(raw, 1):
        at = f"initiatives[{n}]"
        if not isinstance(item, dict):
            error(f"{at} ska vara en tabell")
            continue
        known = {"key", "department", "track", "owner", *_INITIATIVE_INTS}
        for key in item:
            if key not in known:
                error(f"{at}: okänd nyckel {key!r}")
        if not isinstance(item.get("key"), str) or not item["key"].strip():
            error(f"{at}: key saknas")
        if item.get("department") not in departments:
            error(f"{at}: okänt departement {item.get('department')!r}")
        track = item.get("track")
        if track not in TRACKS:
            error(f"{at}: okänt skattespår {track!r} ({', '.join(TRACKS)})")
        owner = item.get("owner")
        if track in TRACKS and track != "partnership" and owner not in founders:
            error(f"{at}: spåret {track} ägs av en grundare; ange owner")
        if track == "partnership" and owner is not None:
            error(f"{at}: spår C fördelas enligt tax.toml; ange ingen owner")
        values = {}
        for key in _INITIATIVE_INTS:
            value = item.get(key, 1 if key == "listed_from" else None)
            if not _int(value) or value < 0:
                error(f"{at}: {key} ska vara ett heltal ≥ 0")
                value = 0
            if key in _BP and value > 10_000:
                error(f"{at}: {key} är baspunkter, högst 10 000")
            values[key] = value
        if values.get("price", 0) <= 0:
            error(f"{at}: price ska vara > 0")
        if values.get("listed_from", 1) < 1:
            error(f"{at}: listed_from ska vara ≥ 1")
        if not errors:
            initiatives.append(Initiative(item["key"], item["department"], track, owner=owner, **values))
    keys = [i.key for i in initiatives]
    if len(keys) != len(set(keys)):
        error("två initiativ har samma key")

    events: list[Event] = []
    for n, item in enumerate(data.get("events", []), 1):
        at = f"events[{n}]"
        if not isinstance(item, dict):
            error(f"{at} ska vara en tabell")
            continue
        for key in item:
            if key not in ("day", "kind", "initiative", "factor_bp", "until", "role", "note"):
                error(f"{at}: okänd nyckel {key!r}")
        kind = item.get("kind")
        if kind not in EVENT_KINDS:
            error(f"{at}: okänd händelse {kind!r} ({', '.join(sorted(EVENT_KINDS))})")
        day = item.get("day")
        if not _int(day) or not 1 <= day <= max(days, 1):
            error(f"{at}: day ska vara 1–{days}")
        until = item.get("until")
        if until is not None and (not _int(until) or not _int(day) or until < day):
            error(f"{at}: until ska vara ≥ day")
        initiative = item.get("initiative")
        if kind in MARKET_EVENTS and initiative not in keys:
            error(f"{at}: {kind} kräver ett initiativ ur [[initiatives]]")
        factor = item.get("factor_bp")
        if kind in ("demand_shock", "cost_spike") and (not _int(factor) or factor < 0):
            error(f"{at}: {kind} kräver factor_bp ≥ 0")
        role = item.get("role")
        if kind in ACTOR_EVENTS and not isinstance(role, str):
            error(f"{at}: {kind} kräver role, till exempel cro eller auditor")
        if not errors:
            events.append(Event(day, kind, initiative, factor, until, role, item.get("note", "")))
    if errors:
        raise ConfigError(errors)
    return Scenario(data["name"], data["description"], data["seed"], days, data["start_date"],
                    tuple(initiatives), tuple(sorted(events, key=lambda e: e.day)))
