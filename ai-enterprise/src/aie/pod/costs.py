"""Kalkyl per order för print-on-demand: Printify till Etsy (arbetsorder 04, D-066).

Allt i USD-cent. Etsys avgifter enligt help.etsy.com, lästa 2026-11-04:
- **Annonsen:** 0,20 USD per annons. När en vara säljs förnyas annonsen, så avgiften kommer igen per såld vara.
- **Transaktionen:** 6,5 % av ordern **inklusive frakt**.
- **Betalningen**, för en säljare med svensk bank: 4 % + 3,00 SEK av pris + frakt + **moms**. Momsen tar Etsy in
  som marknadsplats, men betalningsavgiften räknas på den. Vi antar `tax_on_fee_bp`, normalt 25 %, alltså svensk moms, högst.
- **Offsite Ads:** 15 % på de order som kommer via Etsys annonser, högst 100 USD. Andelen sådana order är
  ett antagande (`offsite_share_bp`).

Printify tar baspris och frakt. Kunden betalar frakten (`shipping_charged`), och den räknas in i avgifterna.

**Skatten** visas på två sätt:
- **På vinsten**, med spår C:s sats (40 %).
- **Som systemets reserv**, på bruttointäkten (`basis = "revenue"` i `tax.toml`). Bedömningen före start (D-058) använder den, och den är den hårdare.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

LISTING = 20
TRANSACTION_BP = 650
PAYMENT_BP = 400
PAYMENT_FIXED = 30  # 3,00 SEK i USD-cent, avrundat uppåt (registret, D-065)
OFFSITE_BP, OFFSITE_CAP = 1_500, 10_000


@dataclass(frozen=True, slots=True)
class Unit:
    price: int
    shipping_charged: int
    base_cost: int
    shipping_cost: int
    fees: int
    offsite: int
    profit_before_tax: int
    tax_on_profit: int
    profit_after_tax: int
    margin_bp: int  # vinst efter skatt i baspunkter av vad kunden betalar
    reserve_on_revenue: int  # systemets försiktiga skattereserv (bruttointäkt × spår C)

    def as_dict(self) -> dict:
        return asdict(self)


def _pct(amount: int, bp: int) -> int:
    return -(-amount * bp // 10_000)  # avrundat uppåt, alltid till nackdel för oss


def unit(price: int, base_cost: int, shipping_cost: int, shipping_charged: int | None = None, *,
         tax_on_fee_bp: int = 2_500, offsite_share_bp: int = 0, tax_rate_bp: int = 4_000) -> Unit:
    shipping_charged = shipping_cost if shipping_charged is None else shipping_charged
    order = price + shipping_charged
    fees = (LISTING + _pct(order, TRANSACTION_BP)
            + _pct(order + _pct(order, tax_on_fee_bp), PAYMENT_BP) + PAYMENT_FIXED)
    offsite = _pct(min(_pct(order, OFFSITE_BP), OFFSITE_CAP), offsite_share_bp)
    profit = order - fees - offsite - base_cost - shipping_cost
    tax = max(0, _pct(profit, tax_rate_bp))
    after = profit - tax
    return Unit(price, shipping_charged, base_cost, shipping_cost, fees, offsite, profit, tax, after,
                after * 10_000 // order if order else 0, _pct(order, tax_rate_bp))


def break_even_orders(fixed_cost: int, profit_per_order: int) -> int | None:
    """Hur många order som behövs för att täcka en fast kostnad (till exempel Premium), eller None om aldrig."""
    if profit_per_order <= 0:
        return None
    return -(-fixed_cost // profit_per_order)
