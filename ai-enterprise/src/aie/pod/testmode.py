"""Testläget för print-on-demand (D-070, grundarbeslut Yorgo 2026-11-04).

Ett initiativ med fältet `test_mode` släpps igenom spärren "simulera före start" (D-058) bara om allt
detta gäller. Allt annat stoppas av spärren som förut.

1. **Påslaget:** `[test_mode] enabled = true` i `config/pod.toml`.
2. **Inom 30 dagar:** idag ligger inom `days` dagar från `start` (D-070 punkt 7).
3. **Högst 20:** färre än `max_active_listings` andra testlägesinitiativ är godkända eller aktiva (D-070 punkt 2).
4. **Marginal:** minst `min_margin_bp` per såld vara (D-070 punkt 4). Marginalen räknas med `margin()` på initiativets egna siffror:
   - **Priset** inkluderar frakten ("free shipping").
   - **Kostnaden** är Printifys baspris och den **dyraste** av frakterna till USA och EU.
   - **Etsys avgifter** räknas med `aie.pod.costs`: 0,20 USD per annons, 6,5 % och 4 % + 3 SEK på pris och moms.
   - **Skatten** är `tax_rate_bp` av vinsten.
   - **Marginalen** är vinst efter skatt delat med priset.
   - **Grundarnas tid** räknas inte (D-070 punkt 5).

Testläget ändrar inget annat. Nödstoppet, skyddat läge, stop-loss och budgetmotorn gäller som vanligt.

Initiativets `test_mode` är `{"base_cost_minor", "shipping_us_minor", "shipping_eu_minor"}` i USD-cent, och
`price_minor` är priset till kunden.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from .costs import Unit, unit

FIELDS = ("base_cost_minor", "shipping_us_minor", "shipping_eu_minor")


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def margin(price: int, base_cost: int, shipping_us: int, shipping_eu: int, tax_rate_bp: int = 4_000) -> Unit:
    """Kalkylen per såld vara enligt D-070: frakten ingår i priset, och den dyraste frakten räknas."""
    return unit(price, base_cost, max(shipping_us, shipping_eu), shipping_charged=0, tax_rate_bp=tax_rate_bp)


class TestMode:
    def __init__(self, config: dict, clock: Callable[[], str] = _today) -> None:
        cfg = config.get("test_mode", {})
        self.enabled = bool(cfg.get("enabled", False))
        self.start = cfg.get("start")
        self.days = int(cfg.get("days", 30))
        self.max_active = int(cfg.get("max_active_listings", 20))
        self.min_margin_bp = int(cfg.get("min_margin_bp", 3_000))
        self.tax_rate_bp = int(cfg.get("tax_rate_bp", 4_000))
        self._clock = clock
        if self.enabled and not self.start:
            raise ValueError("pod.toml [test_mode]: start saknas")

    @property
    def end(self) -> str | None:
        return (date.fromisoformat(self.start) + timedelta(days=self.days)).isoformat() if self.start else None

    def problems(self, data: dict, active_others: int) -> list[str]:
        """Varför initiativet inte får gå igenom testläget. Tom lista betyder att det får gå igenom."""
        if not self.enabled:
            return ["testläget är avstängt i config/pod.toml (D-070)"]
        today = self._clock()[:10]
        if not self.start <= today < self.end:
            return [f"testläget gäller {self.start} till {self.end}, inte {today} (D-070 punkt 7)"]
        tm = data.get("test_mode")
        if not isinstance(tm, dict) or not all(isinstance(tm.get(f), int) and tm[f] >= 0 for f in FIELDS):
            return [f"initiativet saknar test_mode med {', '.join(FIELDS)} i USD-cent (D-070)"]
        if data.get("currency") != "USD":
            return ["testläget räknar i USD (D-070)"]
        out = []
        if active_others >= self.max_active:
            out.append(f"redan {active_others} aktiva annonser i testläget; högst {self.max_active} (D-070 punkt 2)")
        u = margin(data["price_minor"], tm["base_cost_minor"], tm["shipping_us_minor"], tm["shipping_eu_minor"],
                   self.tax_rate_bp)
        if u.margin_bp < self.min_margin_bp:
            out.append(f"marginalen är {u.margin_bp / 100:.1f} %; minst {self.min_margin_bp / 100:.0f} % krävs (D-070 punkt 4)")
        return out
