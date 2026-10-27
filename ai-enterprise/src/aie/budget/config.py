"""Läser `config/budgets.toml` (ER-17, D-026, D-047). Alla fel samlas och kastas som `ConfigError`.

Två lägen (`mode`):
- `fixed` (D-026, standard): varje departement har en fast `budget` för miljöns livstid. Kostnader
  och plattformsavgifter räknas mot budgeten.
- `capital` (D-047): varje departement har en andel (`share`, procent) av det **disponibla kapitalet**
  i stället för ett fast belopp. Disponibelt kapital är likvida medel minus reserv, åtaganden och
  reserverad skatt. Budgeten växer när verksamheten går med vinst och krymper vid förlust, och den har
  ingen period. Plattformsavgifter är försäljningskostnader: de dras från intäkterna i resultatet men
  belastar inte departementets budget.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..config import ConfigError
from ..config.models import RiskLimits

BUDGETS_FILE = "budgets.toml"


class Risk(str, Enum):
    """Riskklasser (§24). `critical` får aldrig vara ett departements riskutrymme."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

_KEYS = ("budget", "max_commitment", "risk_room", "purpose")
_CAPITAL_KEYS = ("share", "max_commitment", "risk_room", "purpose")
MODES = ("fixed", "capital")


@dataclass(frozen=True, slots=True)
class Budget:
    department: str
    budget_minor: int | None  # None i kapitalläget: budgeten räknas från det disponibla kapitalet
    max_commitment_minor: int
    risk_room: Risk
    purpose: str
    share_percent: int | None = None  # kapitalläget (D-047): andel av det disponibla kapitalet

    @property
    def capital_based(self) -> bool:
        return self.share_percent is not None


def load_budgets(
    config_dir: Path | str, departments: Iterable[str], limits: RiskLimits
) -> dict[str, Budget]:
    path = Path(config_dir) / BUDGETS_FILE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{BUDGETS_FILE}: filen saknas i {config_dir}"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(
            [f"{BUDGETS_FILE}: kan inte tolkas som TOML: {exc}"]
        ) from None

    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(f"{BUDGETS_FILE}: {message}")

    for key in data:
        if key not in ("config_version", "mode", "departments"):
            error(f"okänd nyckel {key!r}")
    mode = data.get("mode", "fixed")
    if mode not in MODES:
        error(f"mode = {mode!r} stöds inte (fixed eller capital)")
        mode = "fixed"
    keys = _CAPITAL_KEYS if mode == "capital" else _KEYS
    if data.get("config_version") != 1 or isinstance(data.get("config_version"), bool):
        error(
            f"config_version = {data.get('config_version')!r} stöds inte (förväntat 1)"
        )
    entries = data.get("departments", {})
    if not isinstance(entries, dict):
        error("[departments] måste vara en tabell")
        entries = {}
    known = frozenset(departments)
    cap = limits.max_department_budget
    budgets: dict[str, Budget] = {}
    for name, entry in entries.items():
        where = f"departments.{name}"
        if name not in known:
            error(f"{where}: okänt departement (kända: {', '.join(sorted(known))})")
            continue
        if not isinstance(entry, dict):
            error(f"{where} måste vara en tabell")
            continue
        for key in entry:
            if key not in keys:
                error(f"{where}: okänd nyckel {key!r} (tillåtna i läget {mode}: {', '.join(keys)})")
        values = {"budget": None, "share": None}
        if mode == "capital":
            share = entry.get("share")
            if not isinstance(share, int) or isinstance(share, bool) or not 1 <= share <= 100:
                error(f"{where}.share måste vara en procentsats 1–100 av det disponibla kapitalet (D-047)")
                share = None
            values["share"] = share
        for key in (("max_commitment",) if mode == "capital" else ("budget", "max_commitment")):
            value = entry.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                error(
                    f"{where}.{key} måste vara ett positivt heltal; en saknad gräns betyder blockera (ER-02)"
                )
                value = None
            values[key] = value
        if mode == "fixed" and values["budget"] is not None:
            if cap is None:
                error(
                    f"{where}: MAX_DEPARTMENT_BUDGET saknas i risk_limits.toml (ER-02)"
                )
            elif values["budget"] > cap.amount_minor:
                error(
                    f"{where}.budget = {values['budget']} är över MAX_DEPARTMENT_BUDGET ({cap.amount_minor})"
                )
            if (
                values["max_commitment"] is not None
                and values["max_commitment"] > values["budget"]
            ):
                error(f"{where}.max_commitment får inte vara större än budget")
        try:
            room = Risk(entry.get("risk_room"))
        except ValueError:
            room = None
        if room is None or room is Risk.CRITICAL:
            error(f"{where}.risk_room måste vara low, medium eller high")
        purpose = entry.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            error(f"{where}.purpose saknas (ER-17: användningsområde)")
        if not errors:
            budgets[name] = Budget(
                name, values["budget"], values["max_commitment"], room, purpose.strip(), values["share"]
            )
    if limits.start_capital is None or limits.minimum_reserve is None:
        error(
            "START_CAPITAL och MINIMUM_RESERVE måste finnas för att reserven ska kunna skyddas (ER-02, ER-05)"
        )
    elif mode == "capital":
        total_share = sum(b.share_percent for b in budgets.values())
        if total_share > 100:
            error(f"andelarna summerar till {total_share} %; högst 100 % av det disponibla kapitalet (D-047)")
    else:
        free = limits.start_capital.amount_minor - limits.minimum_reserve.amount_minor
        total = sum(b.budget_minor for b in budgets.values())
        if total > free:
            error(
                f"summan av budgetarna ({total}) äter av den skyddade reserven (högst {free}, §5)"
            )
    if errors:
        raise ConfigError(errors)
    return budgets

