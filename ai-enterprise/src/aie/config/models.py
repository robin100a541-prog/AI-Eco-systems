"""Oföränderliga konfigurationsobjekt (FR-02). Skapas bara av `loader.load_config`."""
from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal
from pathlib import Path

SIM_CURRENCY = "SIM"


@dataclass(frozen=True, slots=True)
class Money:
    """Belopp som heltal i minsta enhet (öre/cent) plus valuta (D-006). Aldrig flyttal (ER-01)."""

    amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class SystemConfig:
    environment: str  # "sim" eller "prod"
    data_dir: Path  # relativt repots rot
    log_dir: Path
    base_currency: str
    config_version: int
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR eller CRITICAL (Fas 1.3)

    @property
    def is_simulation(self) -> bool:
        return self.environment == "sim"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Gränserna i konstitutionens §25 plus API-gränserna i D-009.

    `None` betyder att parametern saknas. Det får bara förekomma i `sim`, och en
    handling som behöver gränsen ska då blockeras, aldrig behandlas som obegränsad (ER-02).
    Procentsatser är `Decimal` i intervallet 0–100.
    """

    currency: str
    start_capital: Money | None
    minimum_reserve: Money | None
    max_total_drawdown: Decimal | None
    max_single_experiment_loss: Money | None
    max_department_budget: Money | None
    max_single_transaction: Money | None
    max_committed_capital: Money | None
    max_allowed_unverified_spend: Money | None
    human_approval_threshold: Money | None
    reinvestment_policy: Decimal | None
    api_reinvest_share: Decimal | None
    api_monthly_cap: Money | None

    @property
    def missing(self) -> tuple[str, ...]:
        """Namnen (som i risk_limits.toml) på de gränser som saknas."""
        return tuple(
            f.name.upper()
            for f in fields(self)
            if f.name != "currency" and getattr(self, f.name) is None
        )


@dataclass(frozen=True, slots=True)
class Config:
    system: SystemConfig
    risk: RiskLimits
    warnings: tuple[str, ...] = ()
