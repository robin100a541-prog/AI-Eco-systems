"""Tester för designer, kalkyl och Q4-flödet (arbetsorder 04, D-066, D-067). Inga nätverksanrop."""
import shutil
import unittest
import zlib
from pathlib import Path

from aie.pod import costs, q4
from aie.pod.designs import FONT, read_png_size, render_pattern, render_text, write_png

from .pod_helpers import tmpdir

ROOT = Path(__file__).resolve().parents[2]


class TestDesigns(unittest.TestCase):
    def test_png_has_the_print_size_alpha_and_300_dpi(self):
        """Verifies D-067: PNG (Printify tar inte SVG) i tryckstorlek, med transparent bakgrund och 300 dpi."""
        path = write_png(render_text("COZY\nSEASON", 450, 540), tmpdir(self) / "d.png")
        data = path.read_bytes()
        self.assertEqual(read_png_size(path), (450, 540))
        self.assertEqual(data[24:26], b"\x08\x06")  # 8 bitar, RGBA
        self.assertIn(b"pHYs", data)
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        self.assertEqual(raw[1:5], b"\x00\x00\x00\x00")  # hörnet är transparent
        self.assertIn(b"\x1f\x2d\x2a\xff", raw)  # texten finns, i rätt färg

    def test_text_that_does_not_fit_or_unknown_glyphs_are_refused(self):
        """Verifies D-067: inga tysta fel i ett motiv."""
        with self.assertRaisesRegex(ValueError, "saknar"):
            render_text("JUL ÅÄÖ", 900, 900)
        with self.assertRaisesRegex(ValueError, "plats"):
            render_text("A VERY LONG LINE OF TEXT THAT CANNOT FIT", 20, 20)
        for kind in ("snowflake", "check", "stripes"):
            img = render_pattern(kind, 120, 60)
            self.assertEqual((img.width, len(img.rows), len(img.rows[0])), (120, 60, 480))
        self.assertEqual(len(FONT["A"]), 7)


class TestCosts(unittest.TestCase):
    def test_etsy_fees_follow_the_verified_formula(self):
        """Verifies D-066: 0,20 + 6,5 % av pris och frakt + 4 % av pris, frakt och moms + 3 SEK; skatt 40 % av vinsten."""
        u = costs.unit(2_499, 1_100, 500)
        self.assertEqual(u.fees, 20 + 195 + 150 + 30)  # 6,5 % av 29,99 = 1,95; 4 % av 37,49 = 1,50
        self.assertEqual((u.profit_before_tax, u.tax_on_profit, u.profit_after_tax), (1_004, 402, 602))
        self.assertEqual(u.reserve_on_revenue, 1_200)
        ads = costs.unit(2_499, 1_100, 500, offsite_share_bp=10_000)
        self.assertEqual(ads.offsite, 450)  # 15 % av 29,99
        self.assertEqual(costs.unit(500, 1_000, 500).tax_on_profit, 0)  # ingen skatt på förlust
        self.assertEqual(costs.break_even_orders(3_900, 602), 7)  # Premium 39 USD/mån
        self.assertIsNone(costs.break_even_orders(3_900, 0))


class TestQ4(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self) / "q4"
        self.dir.mkdir()
        shutil.copy(ROOT / "products" / "q4" / "ideas.toml", self.dir / "ideas.toml")

    def test_all_ten_ideas_pass_the_rules_and_get_a_design_and_a_calculation(self):
        """Verifies D-066 och D-067: tio egna idéer, regler, PNG och kalkyl; rapporten säger att det är utkast."""
        result = q4.run(ROOT / "config", self.dir, "yorgo", gate=False)
        self.assertEqual(len(result["results"]), 10)
        for key, r in result["results"].items():
            with self.subTest(key):
                self.assertEqual(r["problems"], [])
                self.assertTrue((self.dir / key / "design.png").is_file())
                self.assertIn("UTKAST", (self.dir / key / "README.md").read_text(encoding="utf-8"))
        self.assertIn("Inget är publicerat", (self.dir / "REPORT.md").read_text(encoding="utf-8"))

    def test_an_idea_with_a_trademark_is_stopped_and_gets_no_design(self):
        """Verifies D-067: ett motiv med ett varumärke stoppas före design och kalkyl."""
        text = (self.dir / "ideas.toml").read_text(encoding="utf-8")
        (self.dir / "ideas.toml").write_text(text.replace('text = "COZY\\nSEASON"', 'text = "GRINCH\\nSEASON"'),
                                             encoding="utf-8")
        result = q4.run(ROOT / "config", self.dir, "yorgo", gate=False)
        stopped = result["results"]["q4-cozy-season-mug"]
        self.assertTrue(any("Grinch" in p for p in stopped["problems"]))
        self.assertFalse((self.dir / "q4-cozy-season-mug" / "design.png").exists())
        self.assertNotIn("q4-cozy-season-mug", result["ranked"])

    def test_a_real_catalog_snapshot_replaces_the_assumed_shipping(self):
        """Verifies D-066: Printifys verkliga frakt ersätter antagandet och märks som verifierad."""
        products = q4.load_ideas(self.dir / "ideas.toml")["products"]
        catalog = {"read_on": "2026-11-05", "snapshots": [{"title": "Ceramic Mug 11oz", "variants": [{"cost_minor": None}],
                                                           "shipping_standard": {"US": {"first_item_minor_max": 649,
                                                                                        "currency": "USD"}}}]}
        mug = q4.apply_catalog(products, catalog)["mug"]
        self.assertEqual(mug["shipping_us"], 649)
        self.assertEqual(mug["verified"], ["frakt till USA från Printifys API (2026-11-05)"])
        self.assertEqual(mug["base_cost"], products["mug"]["base_cost"])  # baspriset finns inte i katalogen
