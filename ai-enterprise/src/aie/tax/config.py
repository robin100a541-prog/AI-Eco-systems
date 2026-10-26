"""Läser `config/tax.toml` (Fas 4f, D-032). Alla fel samlas och kastas som `ConfigError`."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..config import ConfigError

TAX_FILE = "tax.toml"
TRACKS = {
    "isk": "A. Investeringssparkonto (ISK)",
    "self_employment": "B. Egenanställning",
    "partnership": "C. Enkelt bolag",
    "hobby": "D. Hobby (T2)",
}
_KEYS = ("config_version", "currency", "vat_threshold", "vat_warning_percent", "untracked_rate", "rates",
         "partnership_shares")


@dataclass(frozen=True, slots=True)
class TaxConfig:
    currency: str
    vat_threshold_minor: int
    vat_warning_percent: int
    untracked_rate_bp: int
    rates_bp: dict[str, int]
    partnership_shares_bp: dict[str, int]


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_tax_config(config_dir: Path | str, founders: tuple[str, ...] | frozenset[str]) -> TaxConfig:
    path = Path(config_dir) / TAX_FILE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{TAX_FILE}: filen saknas i {config_dir}"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError([f"{TAX_FILE}: kan inte tolkas som TOML: {exc}"]) from None

    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(f"{TAX_FILE}: {message}")

    for key in data:
        if key not in _KEYS:
            error(f"okänd nyckel {key!r}")
    if data.get("config_version") != 1 or isinstance(data.get("config_version"), bool):
        error(f"config_version = {data.get('config_version')!r} stöds inte (förväntat 1)")
    currency = data.get("currency")
    if not (isinstance(currency, str) and len(currency) == 3 and currency.isupper()):
        error("currency ska vara tre versaler, till exempel SIM eller SEK (D-006)")
    threshold = data.get("vat_threshold")
    if not _int(threshold) or threshold <= 0:
        error("vat_threshold ska vara ett heltal > 0 i minsta enhet (ER-20)")
    warning = data.get("vat_warning_percent")
    if not _int(warning) or not 0 < warning < 100:
        error("vat_warning_percent ska vara ett heltal mellan 1 och 99")
    untracked = data.get("untracked_rate")
    if not _int(untracked) or not 0 <= untracked <= 10_000:
        error("untracked_rate ska vara baspunkter 0–10 000")
    rates = data.get("rates")
    if not isinstance(rates, dict) or set(rates) != set(TRACKS):
        error(f"[rates] ska ha exakt spåren {', '.join(TRACKS)} (D-010)")
        rates = {}
    for track, rate in rates.items():
        if not _int(rate) or not 0 <= rate <= 10_000:
            error(f"rates.{track} ska vara baspunkter 0–10 000")
    if _int(untracked) and rates and all(_int(r) for r in rates.values()) and untracked < max(rates.values()):
        error("untracked_rate ska vara minst lika hög som den högsta satsen; en intäkt utan spår reserveras försiktigt")
    shares = data.get("partnership_shares")
    if not isinstance(shares, dict) or set(shares) != set(founders):
        error(f"[partnership_shares] ska ha exakt grundarna {', '.join(sorted(founders))}")
        shares = {}
    elif not all(_int(v) and v >= 0 for v in shares.values()) or sum(shares.values()) != 10_000:
        error("partnership_shares ska vara baspunkter som summerar till 10 000")
    if errors:
        raise ConfigError(errors)
    return TaxConfig(currency, threshold, warning, untracked, dict(rates), dict(shares))
