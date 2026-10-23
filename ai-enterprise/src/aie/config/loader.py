"""Läser och validerar `config/*.toml` (FR-02, ER-02, ER-15, SR-10).

Valideringen går igenom allt och samlar **alla** fel innan den ger upp. Den som rättar
konfigurationen ska se hela listan på en gång, inte ett fel per körning.

Ordning:
1. Läs varje `*.toml` i mappen och sök efter hemligheter i alla filer (SR-10).
2. Validera `system.toml`: miljö, sökvägar, valuta, version.
3. Validera `risk_limits.toml` mot tabellen `LIMITS` och mot miljön i steg 2.
4. Kontrollera att filerna passar ihop (samma valuta).
Finns minst ett fel kastas `ConfigError` med hela listan. Annars returneras en fryst `Config`.
"""
from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import SIM_CURRENCY, Config, Money, RiskLimits, SystemConfig

SYSTEM_FILE = "system.toml"
RISK_FILE = "risk_limits.toml"
SUPPORTED_CONFIG_VERSION = 1
ENVIRONMENTS = ("sim", "prod")

AMOUNT = "belopp"  # heltal i minsta enhet, >= 0
PERCENT = "procent"  # tal 0–100

# Alla tillåtna gränser och deras typ. De tio första är §25, de två sista D-009.
LIMITS: dict[str, str] = {
    "START_CAPITAL": AMOUNT,
    "MINIMUM_RESERVE": AMOUNT,
    "MAX_TOTAL_DRAWDOWN": PERCENT,
    "MAX_SINGLE_EXPERIMENT_LOSS": AMOUNT,
    "MAX_DEPARTMENT_BUDGET": AMOUNT,
    "MAX_SINGLE_TRANSACTION": AMOUNT,
    "MAX_COMMITTED_CAPITAL": AMOUNT,
    "MAX_ALLOWED_UNVERIFIED_SPEND": AMOUNT,
    "HUMAN_APPROVAL_THRESHOLD": AMOUNT,
    "REINVESTMENT_POLICY": PERCENT,
    "API_REINVEST_SHARE": PERCENT,
    "API_MONTHLY_CAP": AMOUNT,
}
SYSTEM_KEYS = ("config_version", "environment", "data_dir", "log_dir", "base_currency")
RISK_KEYS = ("currency", *LIMITS)

_CURRENCY_CODE = re.compile(r"[A-Z]{3}")
_SECRET_NAMES = {"key", "token", "secret", "password", "passwd"}
_SECRET_SUFFIXES = ("_key", "_token", "_secret", "_password")
_SECRET_FILE_SUFFIXES = (".env", ".secret", ".key", ".pem")


class ConfigError(Exception):
    """Konfigurationen är ogiltig. `errors` innehåller varje fel, `warnings` varje varning."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None) -> None:
        self.errors = tuple(errors)
        self.warnings = tuple(warnings or ())
        lines = [f"Konfigurationen är ogiltig ({len(self.errors)} fel):"]
        lines += [f"  - {e}" for e in self.errors]
        if self.warnings:
            lines.append(f"Varningar ({len(self.warnings)}):")
            lines += [f"  - {w}" for w in self.warnings]
        super().__init__("\n".join(lines))


@dataclass
class _Problems:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


def load_config(config_dir: Path | str = "config") -> Config:
    """Läser `system.toml` och `risk_limits.toml` i `config_dir`. Kastar `ConfigError` vid fel."""
    config_dir = Path(config_dir)
    problems = _Problems()
    if not config_dir.is_dir():
        problems.error(str(config_dir), "konfigurationsmappen finns inte")
        raise ConfigError(problems.errors)

    documents = _read_all(config_dir, problems)
    for name, data in documents.items():
        _reject_secrets(name, data, problems)

    system = _parse_system(documents.get(SYSTEM_FILE), problems)
    # Miljön styr reglerna för risk_limits.toml även om andra fält i system.toml är fel.
    environment = (documents.get(SYSTEM_FILE) or {}).get("environment")
    risk = _parse_risk(documents.get(RISK_FILE), environment, problems)

    if system and risk and system.base_currency != risk.currency:
        problems.error(
            RISK_FILE,
            f"currency = {risk.currency!r} matchar inte base_currency = "
            f"{system.base_currency!r} i {SYSTEM_FILE}",
        )

    if problems.errors or system is None or risk is None:
        raise ConfigError(problems.errors, problems.warnings)
    return Config(system=system, risk=risk, warnings=tuple(problems.warnings))


# --- Läsning och hemligheter ------------------------------------------------------------


def _read_all(config_dir: Path, problems: _Problems) -> dict[str, dict[str, Any] | None]:
    """Läser varje *.toml i mappen. En fil som inte kan tolkas blir `None` och ett fel."""
    for path in sorted(config_dir.iterdir()):
        if path.name.lower().endswith(_SECRET_FILE_SUFFIXES):
            problems.error(path.name, "filer med hemligheter hör inte hemma i config/ (SR-10)")

    documents: dict[str, dict[str, Any] | None] = {}
    for path in sorted(config_dir.glob("*.toml")):
        try:
            documents[path.name] = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            problems.error(path.name, f"kan inte tolkas som TOML: {exc}")
            documents[path.name] = None

    for required in (SYSTEM_FILE, RISK_FILE):
        if required not in documents:
            problems.error(required, "filen saknas")
    return documents


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SECRET_NAMES or lowered.endswith(_SECRET_SUFFIXES)


def _reject_secrets(where: str, data: Any, problems: _Problems, prefix: str = "") -> None:
    """Hittar nycklar som ser ut som hemligheter, även i tabeller. Värdet skrivs aldrig ut."""
    if isinstance(data, list):
        for item in data:
            _reject_secrets(where, item, problems, prefix)
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if _is_secret_key(key):
            problems.error(
                where,
                f"{dotted} ser ut som en hemlighet; hemligheter läses från miljövariabler (SR-10)",
            )
        _reject_secrets(where, value, problems, prefix=f"{dotted}.")


def _reject_unknown_keys(
    where: str, data: dict[str, Any], allowed: tuple[str, ...], problems: _Problems
) -> None:
    for key in data:
        if key not in allowed and not _is_secret_key(key):  # hemligheter rapporteras redan
            problems.error(where, f"okänd nyckel {key!r} (stavfel? tillåtna: {', '.join(allowed)})")


# --- system.toml --------------------------------------------------------------------------


def _parse_system(data: dict[str, Any] | None, problems: _Problems) -> SystemConfig | None:
    if data is None:
        return None
    where = SYSTEM_FILE
    errors_before = len(problems.errors)
    _reject_unknown_keys(where, data, SYSTEM_KEYS, problems)

    version = data.get("config_version")
    if version is None:
        problems.error(where, "config_version saknas")
    elif not _is_int(version) or version != SUPPORTED_CONFIG_VERSION:
        problems.error(
            where, f"config_version = {version!r} stöds inte (förväntat {SUPPORTED_CONFIG_VERSION})"
        )

    environment = data.get("environment")
    if environment is None:
        problems.error(where, 'environment saknas (måste vara "sim" eller "prod")')
    elif environment not in ENVIRONMENTS:
        problems.error(where, f'environment = {environment!r} är okänd (måste vara "sim" eller "prod")')

    dirs = {name: _parse_dir(where, name, data.get(name), problems) for name in ("data_dir", "log_dir")}
    currency = _parse_currency(where, "base_currency", data.get("base_currency"), environment, problems)

    if len(problems.errors) > errors_before:
        return None
    return SystemConfig(
        environment=environment,
        data_dir=dirs["data_dir"],
        log_dir=dirs["log_dir"],
        base_currency=currency,
        config_version=version,
    )


def _parse_dir(where: str, name: str, value: Any, problems: _Problems) -> Path | None:
    if value is None:
        problems.error(where, f"{name} saknas")
    elif not isinstance(value, str) or not value.strip():
        problems.error(where, f"{name} måste vara en icke-tom sökväg, fick {value!r}")
    else:
        return Path(value)
    return None


def _parse_currency(
    where: str, name: str, value: Any, environment: Any, problems: _Problems
) -> str | None:
    """Valutakod med tre versaler. `SIM` hör till sim och verkliga valutor till prod (ER-15)."""
    if value is None:
        problems.error(where, f"{name} saknas")
        return None
    if not isinstance(value, str) or not _CURRENCY_CODE.fullmatch(value):
        problems.error(where, f"{name} = {value!r} är ingen valutakod (tre versaler, t.ex. SEK eller SIM)")
        return None
    if environment == "prod" and value == SIM_CURRENCY:
        problems.error(where, f"{name} = 'SIM' är inte tillåtet i prod: simulerade pengar är inte kapital (ER-15)")
        return None
    if environment == "sim" and value != SIM_CURRENCY:
        problems.error(where, f"{name} = {value!r} är en verklig valuta; i sim måste valutan vara 'SIM' (ER-15)")
        return None
    return value


# --- risk_limits.toml ---------------------------------------------------------------------


def _parse_risk(
    data: dict[str, Any] | None, environment: Any, problems: _Problems
) -> RiskLimits | None:
    if data is None:
        return None
    where = RISK_FILE
    errors_before = len(problems.errors)
    _reject_unknown_keys(where, data, RISK_KEYS, problems)
    currency = _parse_currency(where, "currency", data.get("currency"), environment, problems)

    # Belopp valideras som heltal oberoende av valutan, så att en felaktig valuta inte
    # döljer andra fel. Först när allt är giltigt kopplas valutan på (Money).
    values: dict[str, int | Decimal | None] = {}
    for name, kind in LIMITS.items():
        raw = data.get(name)
        if raw is None:
            _report_missing_limit(where, name, environment, problems)
            values[name] = None
        elif kind == AMOUNT:
            values[name] = _parse_amount(where, name, raw, problems)
        else:
            values[name] = _parse_percent(where, name, raw, problems)

    start, reserve = values["START_CAPITAL"], values["MINIMUM_RESERVE"]
    if isinstance(start, int) and isinstance(reserve, int) and reserve > start:
        problems.error(
            where,
            f"MINIMUM_RESERVE ({reserve}) är större än START_CAPITAL ({start}); "
            "reserven kan inte vara större än kapitalet (§5, ER-05)",
        )

    if len(problems.errors) > errors_before or currency is None:
        return None
    limits = {
        name.lower(): Money(value, currency) if LIMITS[name] == AMOUNT and value is not None else value
        for name, value in values.items()
    }
    return RiskLimits(currency=currency, **limits)


def _report_missing_limit(where: str, name: str, environment: Any, problems: _Problems) -> None:
    """ER-02: en saknad gräns betyder blockera, aldrig obegränsat.

    Bara i `sim` blir det en varning. I prod, och när miljön är okänd, är det ett fel.
    """
    if environment == "sim":
        problems.warn(where, f"{name} saknas; handlingar som behöver gränsen blockeras (ER-02)")
    else:
        problems.error(where, f"{name} saknas; i prod måste alla gränser vara satta (ER-02)")


def _parse_amount(where: str, name: str, raw: Any, problems: _Problems) -> int | None:
    if not _is_int(raw):
        problems.error(where, f"{name} = {raw!r} måste vara ett heltal i minsta enhet (öre/cent) (D-006)")
    elif raw < 0:
        problems.error(where, f"{name} = {raw} är negativt; belopp måste vara >= 0")
    else:
        return raw
    return None


def _parse_percent(where: str, name: str, raw: Any, problems: _Problems) -> Decimal | None:
    if not (_is_int(raw) or isinstance(raw, float)) or (isinstance(raw, float) and not math.isfinite(raw)):
        problems.error(where, f"{name} = {raw!r} måste vara en procentsats (tal 0–100)")
    elif not 0 <= raw <= 100:
        problems.error(where, f"{name} = {raw} ligger utanför 0–100 procent")
    else:
        return Decimal(str(raw))  # via str: 12.5 blir exakt 12.5, inte binärt avrundat
    return None


def _is_int(value: Any) -> bool:
    """`True`/`False` är tekniskt `int` i Python men är aldrig ett giltigt belopp."""
    return isinstance(value, int) and not isinstance(value, bool)
