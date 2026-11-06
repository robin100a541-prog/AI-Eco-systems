"""Tester för testläget för print-on-demand (D-070). Verifierar att testlägets produkter går igenom spärren
(D-058) och att allt annat fortfarande stoppas."""
import unittest

from aie.pod.testmode import TestMode, margin
from aie.registry import RegistryError

from .test_registry import INITIATIVE, PLATFORM, RegisterCase

CFG = {"test_mode": {"enabled": True, "start": "2026-11-06", "days": 30, "max_active_listings": 20,
                     "min_margin_bp": 3_000, "tax_rate_bp": 4_000}}
# En t-shirt med frakt inräknad: baspris 9,00 USD (antaget), frakt 4,95 till USA och 10,39 till EU (Printifys API
# 2026-11-06). Med den dyraste frakten krävs omkring 52 USD för 30 %; 34,99 USD ger bara 19 %.
TEE = {"base_cost_minor": 900, "shipping_us_minor": 495, "shipping_eu_minor": 1_039}


def pod(price=5_499, **tm):
    return dict(INITIATIVE, platform="etsy", currency="USD", price_minor=price, unit_cost_minor=0,
                test_mode=dict(TEE, **tm))


class TestMargin(unittest.TestCase):
    def test_margin_uses_the_dearest_shipping_and_tax_on_profit(self):
        """Verifies D-070 punkt 4: frakten ingår i priset, den dyraste frakten, Etsys avgifter och 40 % skatt."""
        u = margin(3_499, 900, 495, 1_039)
        self.assertEqual(u.shipping_cost, 1_039)
        self.assertEqual(u.shipping_charged, 0)
        self.assertEqual(u.fees, 20 + 228 + 175 + 30)  # 6,5 % av 34,99; 4 % av 34,99 + 25 % moms
        self.assertEqual(u.profit_before_tax, 3_499 - 453 - 900 - 1_039)
        self.assertEqual(u.margin_bp, u.profit_after_tax * 10_000 // 3_499)
        self.assertEqual(u.margin_bp // 100, 18)  # 18,9 %: under gränsen
        self.assertGreaterEqual(margin(5_499, 900, 495, 1_039).margin_bp, 3_000)


class TestGate(RegisterCase):
    def setUp(self):
        super().setUp()
        self.today = "2026-11-07"
        self.register.test_mode = TestMode(CFG, clock=lambda: self.today)
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "platform", "etsy", status, PLATFORM, "test")

    def approve(self, key, data):
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "initiative", key, status, data, "test")
        if self.register.get("platform", "etsy").status == "reviewed":
            self.register.set_status("yorgo", "platform", "etsy", "approved", "test")
        self.register.set_status("yorgo", "initiative", key, "approved", "test")

    def test_a_test_mode_product_with_enough_margin_passes_without_ready(self):
        """Verifies D-070 punkt 2: godkänd och får utgifter utan simuleringens "redo"."""
        self.approve("tee-1", pod())
        self.assertEqual(self.register.get("initiative", "tee-1").status, "approved")
        self.assertIsNone(self.register.spend_block_reason("research", "tee-1"))

    def test_everything_else_is_still_stopped(self):
        """Verifies D-058 och D-070: utan test_mode, under 30 %, efter 30 dagar eller avstängt stoppas initiativet."""
        self.approve("good", pod())  # plattformen godkänns via en produkt som klarar testläget
        cases = {
            "utan testläge": (dict(INITIATIVE, platform="etsy"), "simulera före start"),
            "för låg marginal": (pod(price=3_499), "marginalen"),
            "saknar kostnad": (pod(base_cost_minor=None), "saknar test_mode"),
        }
        for name, (data, message) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(RegistryError, message):
                self.approve(f"x-{len(name)}", data)
        self.today = "2026-12-06"  # 30 dagar efter start
        with self.assertRaisesRegex(RegistryError, "testläget gäller 2026-11-06 till 2026-12-06"):
            self.approve("late", pod())
        self.today = "2026-11-07"
        self.register.test_mode = TestMode({"test_mode": dict(CFG["test_mode"], enabled=False)})
        with self.assertRaisesRegex(RegistryError, "avstängt"):
            self.approve("off", pod())

    def test_at_most_20_active_listings(self):
        """Verifies D-070 punkt 2: den 21:a produkten i testläget stoppas."""
        for n in range(20):
            self.approve(f"tee-{n}", pod())
        with self.assertRaisesRegex(RegistryError, "redan 20 aktiva"):
            self.approve("tee-20", pod())
        self.register.set_status("yorgo", "initiative", "tee-0", "retired", "test")  # en plats blir ledig
        self.approve("tee-20", pod())
