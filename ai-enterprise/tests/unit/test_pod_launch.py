"""Tester för lanseringen Q4 (LANSERING-Q4.md, D-070): arabisk formning, designer, val av tryckeri, pris,
opublicerade produkter, LISTA.md, publicering med godkännande och ordrar i ledgern. Inget nätverk."""
import json
import unittest
from pathlib import Path

from aie.config import load_config
from aie.memory import Database
from aie.pod import launch
from aie.pod.design.arabic import shape
from aie.pod.printify import PrintifyClient, PrintifyDrafter, PrintifyReader, load_pod_config
from aie.pod.rules import load_blocklist
from aie.pod.testmode import TestMode
from aie.simulation.agents import ensure_org
from aie.system import build_system

from .pod_helpers import FakeTransport, pod_config, tmpdir

ROOT = Path(__file__).resolve().parents[2]
try:
    import PIL  # noqa: F401  Pillow används bara i aie.pod.design (D-070 punkt 8)
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def ship(us, eu=None, row=None):
    rows = [{"attributes": {"country": {"code": "US"}, "shippingCost": {"firstItem": {"amount": us, "currency": "USD"}}}}]
    if eu is not None:
        rows.append({"attributes": {"country": {"code": "DE"}, "shippingCost": {"firstItem": {"amount": eu, "currency": "USD"}}}})
    if row is not None:
        rows.append({"attributes": {"country": {"code": "REST_OF_THE_WORLD"},
                                    "shippingCost": {"firstItem": {"amount": row, "currency": "USD"}}}})
    return {"data": rows}


class TestArabic(unittest.TestCase):
    def test_letters_join_lam_alef_becomes_a_ligature_and_the_order_is_reversed(self):
        """Verifies D-070: arabisk text formas rätt utan raqm."""
        self.assertEqual(shape("لا"), "ﻻ")  # lam-alef, isolerad
        self.assertEqual(shape("بطلي"), "ﻲﻠﻄﺑ")  # be först, ta och lam mitt, ye sist; omvänt
        with self.assertRaises(ValueError):
            shape("أولاً")  # tanween stöds inte och stoppas


class TestDesigns(unittest.TestCase):
    def test_all_20_designs_pass_the_rules_and_a_trademark_is_stopped(self):
        """Verifies D-067: 20 egna designer, 13 taggar var, inga varumärken."""
        designs = launch.load_designs(ROOT / "products" / "q4" / "designs.toml")
        rules = load_pod_config(ROOT / "config")["etsy"]["listing_rules"]
        blocklist = load_blocklist(ROOT / "config")
        self.assertEqual(len(designs), 20)
        self.assertEqual({k: v for k, v in launch.check_designs(designs, rules, blocklist).items() if v}, {})
        bad = [dict(designs[0], lines=["GRINCH", "SEASON"])]
        self.assertTrue(launch.check_designs(bad, rules, blocklist)[designs[0]["key"]])

    @unittest.skipUnless(HAS_PIL, "Pillow finns inte")
    def test_rendered_png_has_print_size_transparency_and_300_dpi(self):
        """Verifies D-070: PNG i tryckstorlek, transparent, 300 dpi, med typsnitt som har licens i repot."""
        from PIL import Image

        from aie.pod.design import FONTS, font_path, render

        out = render({"lines": ["FIKA ÄR", "VIKTIGT"], "fonts": ["bebas"]}, (900, 1080), tmpdir(self) / "d.png")
        img = Image.open(out)
        self.assertEqual((img.size, img.mode), ((900, 1080), "RGBA"))
        self.assertEqual(img.getpixel((0, 0))[3], 0)
        self.assertEqual(round(img.info["dpi"][0]), 300)
        for key in FONTS:
            self.assertTrue((font_path(key).parent / "OFL.txt").is_file())


class TestPricing(unittest.TestCase):
    def test_provider_with_the_lowest_dearest_shipping_to_us_and_eu_is_chosen(self):
        """Verifies D-070: bara tryckerier som når både USA och EU; lägst dyraste frakt vinner."""
        class Reader:
            def providers(self, bp):
                return [{"id": 1, "title": "bara USA"}, {"id": 2, "title": "dyr EU"}, {"id": 3, "title": "billigast"}]

            def shipping(self, bp, pid):
                from aie.pod.printify import parse_shipping
                return parse_shipping({1: ship(400), 2: ship(450, 2400), 3: ship(500, row=1100)}[pid])

        provider, us, eu = launch.choose_provider(Reader(), 6, ["DE", "SE"])
        self.assertEqual((provider["id"], us, eu), (3, 500, 1100))

    def test_lowest_price_with_30_percent_or_none(self):
        """Verifies D-070 punkt 4: lägsta x,99-pris med minst 30 %, annars ingen."""
        price, u = launch.best_price(900, 495, 1_039, {"min_price": 1_999, "max_price": 5_999}, 4_000, 3_000)
        self.assertGreaterEqual(u.margin_bp, 3_000)
        self.assertEqual(price % 100, 99)
        self.assertLess(launch.best_price(900, 495, 1_039, {"min_price": 1_999, "max_price": price - 100}, 4_000,
                                          3_000) or (0,), (price,))
        self.assertIsNone(launch.best_price(900, 495, 1_039, {"min_price": 1_999, "max_price": 2_999}, 4_000, 3_000))


class PrintifyCase(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.config_dir = pod_config(self.dir)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.system = build_system(load_config(self.config_dir), self.db, self.config_dir)
        ensure_org(self.system.registry, "yorgo")
        self.pod = load_pod_config(self.config_dir)
        self.pod["launch"]["products"] = {"tee": dict(self.pod["launch"]["products"]["tee"], max_price=5_999)}
        self.designs = [{"key": "cozy-season", "lines": ["COZY"], "font": "bebas", "color": "#000000", "products": ["tee"],
                         "title": "Cozy Season Shirt", "tags": [f"tag {i}" for i in range(13)], "pinterest": "Cozy."},
                        {"key": "dyr", "lines": ["DYR"], "font": "bebas", "color": "#000000", "products": ["tee"],
                         "title": "Dyr", "tags": [f"tag {i}" for i in range(13)], "pinterest": "x"}]
        for d in self.designs:
            (self.dir / "q4" / d["key"]).mkdir(parents=True)
            (self.dir / "q4" / d["key"] / "tee.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (4500).to_bytes(4, "big") + (5400).to_bytes(4, "big") + b"\x00" * 20)

    def fake(self, costs):
        variants = [{"id": 11, "title": "White / M", "options": {"color": "White", "size": "M"},
                     "placeholders": [{"position": "front", "width": 4500, "height": 5400}]},
                    {"id": 12, "title": "Black / M", "options": {"color": "Black", "size": "M"}}]
        routes = {
            ("GET", "/v1/catalog/blueprints.json"): [(200, [{"id": 6, "title": "Unisex Heavy Cotton Tee"}], None)],
            ("GET", "/v1/catalog/blueprints/6/print_providers.json"): [(200, [{"id": 99, "title": "P99"}], None)],
            ("GET", "/v2/catalog/blueprints/6/print_providers/99/shipping/standard.json"): [(200, ship(495, row=1039), None)],
            ("GET", "/v1/catalog/blueprints/6/print_providers/99/variants.json"): [(200, {"variants": variants}, None)],
            ("POST", "/v1/uploads/images.json"): [(200, {"id": "img1"}, None)],
            ("POST", "/v1/shops/5/products.json"): [(200, {"id": "p1"}, None), (200, {"id": "p2"}, None)],
            ("GET", "/v1/shops/5/products/p1.json"): [(200, {"variants": [{"id": 11, "cost": costs[0], "is_enabled": True}]}, None)],
            ("GET", "/v1/shops/5/products/p2.json"): [(200, {"variants": [{"id": 11, "cost": costs[1], "is_enabled": True}]}, None)],
            ("PUT", "/v1/shops/5/products/p1.json"): [(200, {}, None)],
        }
        return FakeTransport(routes)

    def prepared(self):
        fake = self.fake([900, 3_000])
        client = PrintifyClient("tok", transport=fake, min_interval=0)
        reader = PrintifyReader(self.system.engine, self.system.audit, "res-1", client)
        drafter = PrintifyDrafter(self.system.engine, self.system.audit, "lead-1", client, self.pod)
        return launch.prepare(reader, drafter, 5, self.designs, self.pod, self.dir / "q4"), fake


class TestPrepare(PrintifyCase):
    def test_unpublished_products_get_real_cost_a_price_with_30_percent_or_are_struck(self):
        """Verifies D-070: opublicerade produkter, verkligt baspris, pris med minst 30 %, annars struken; ingen publicering."""
        results, fake = self.prepared()
        ok, struck = results
        self.assertEqual((ok.printify_id, ok.base_cost_minor, ok.shipping_us_minor, ok.shipping_eu_minor), ("p1", 900, 495, 1_039))
        self.assertGreaterEqual(ok.margin_bp, 3_000)
        self.assertIsNone(ok.struck)
        self.assertEqual(ok.variants, [11])  # bara vita varianter (pod.toml)
        self.assertIn("under 30 %", struck.struck)
        created = next(c for c in fake.calls if c["path"] == "/v1/shops/5/products.json")["body"]
        self.assertIn("help of AI", created["description"])
        self.assertIn("Printify", created["description"])
        self.assertEqual(len(created["tags"]), 13)
        put = next(c for c in fake.calls if c["method"] == "PUT")["body"]
        self.assertEqual(put["variants"], [{"id": 11, "price": ok.price_minor}])
        self.assertFalse(any("publish" in c["path"] for c in fake.calls))


class TestListAndPublish(PrintifyCase):
    def setUp(self):
        super().setUp()
        results, _ = self.prepared()
        launch.save(results, self.dir / "q4" / "printify-products.json")
        self.prepared_data = json.loads((self.dir / "q4" / "printify-products.json").read_text(encoding="utf-8"))
        self.list = launch.write_list(self.prepared_data, self.designs, 10.5, self.dir / "q4" / "LISTA.md")
        self.mode = TestMode({"test_mode": {"enabled": True, "start": "2026-11-06", "days": 30}}, clock=lambda: "2026-11-07")

    def test_the_list_has_margin_in_kr_and_ends_with_the_approval_line(self):
        """Verifies LANSERING-Q4 punkt 6: en rad per produkt med marginal i kr och %, och godkännanderaden sist."""
        text = self.list.read_text(encoding="utf-8")
        self.assertIn("`cozy-season/tee`", text)
        self.assertIn(" kr (", text)
        self.assertIn("STRUKEN", text)
        self.assertTrue(text.rstrip().endswith("Godkänn genom att skriva GODKÄND – namn"))
        self.assertEqual(launch.approved_keys(text), (None, ["cozy-season/tee"]))

    def test_publish_needs_the_approval_line_skips_struck_rows_and_respects_20(self):
        """Verifies D-070 punkt 2: bara med GODKÄND, aldrig strukna, och aldrig över 20 aktiva."""
        published = []
        text = self.list.read_text(encoding="utf-8")
        with self.assertRaisesRegex(PermissionError, "GODKÄND"):
            launch.publish(text, self.prepared_data, published.append, self.mode, 0)
        approved = text + "\nGODKÄND – Yorgo\n"
        self.assertEqual(launch.publish(approved, self.prepared_data, published.append, self.mode, 19),
                         ["cozy-season/tee: publicerad (godkänd av Yorgo)"])
        self.assertEqual(published, ["p1"])
        lines = launch.publish(approved, self.prepared_data, published.append, self.mode, 20)
        self.assertIn("redan 20 aktiva", lines[0])
        crossed = approved.replace("| `cozy-season/tee`", "| ~~`cozy-season/tee`~~")
        self.assertEqual(launch.approved_keys(crossed)[1], [])
        self.assertEqual(published, ["p1"])


class TestOrders(unittest.TestCase):
    def test_orders_are_booked_once_in_sek_and_never_in_sim(self):
        """Verifies ER-15 och D-070: riktiga ordrar i pilotens prod-databas (SEK), en gång per order."""
        from aie.pilot.live import pilot_config

        root = tmpdir(self)
        pconf = pilot_config(pod_config(root / "src"), root / "pilot")
        config = load_config(pconf)
        orders = [{"id": "o1", "created_at": "2026-11-08T10:00:00+00:00", "total_price": 1_400, "total_shipping": 495,
                   "total_tax": 0, "line_items": [{"product_id": "p1", "quantity": 1, "metadata": {"price": 4_599}}]}]
        prepared = {"products": [{"key": "cozy-season/tee", "printify_id": "p1"}]}
        with Database.open(root / "pilot-data", "prod") as db:
            system = build_system(config, db, pconf)
            first = launch.book_orders(system, "yorgo", orders, prepared, 10.5)
            again = launch.book_orders(system, "yorgo", orders, prepared, 10.5)
            entries = [e for e in system.ledger.entries("SEK") if e.external_id]
        self.assertEqual((first["orders"], first["revenue_minor"], first["cost_minor"]), (1, 48_290, 19_898))
        self.assertEqual((again["orders"], again["skipped"]), (0, 1))
        self.assertEqual({e.initiative for e in entries}, {"pod-cozy-season-tee"})
        with Database.open(tmpdir(self) / "sim", "sim") as db:
            cfg = pod_config(tmpdir(self))
            sim = build_system(load_config(cfg), db, cfg)
            with self.assertRaisesRegex(ValueError, "SIM"):
                launch.book_orders(sim, "yorgo", orders, prepared, 10.5)


class TestDependency(unittest.TestCase):
    def test_pillow_is_imported_only_in_pod_design(self):
        """Verifies D-070 punkt 8: Pillow är tillåtet bara i src/aie/pod/design/; resten är standardbiblioteket."""
        import re

        allowed = ROOT / "src" / "aie" / "pod" / "design"
        hits = [str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*.py")
                if allowed not in p.parents and re.search(r"^\s*(import PIL|from PIL)", p.read_text(encoding="utf-8"), re.M)]
        self.assertEqual(hits, [])


class TestAdaptAndRerun(PrintifyCase):
    def test_titles_and_tags_follow_the_product_type(self):
        """Verifies D-067: en tröja heter aldrig mugg; alltid 13 taggar på högst 20 tecken."""
        title, tags = launch.adapt("Arabic Coffee First Mug, Arabic Calligraphy Coffee Cup", ["arabic mug", "coffee mug"], "tee")
        self.assertEqual(title, "Arabic Coffee First Shirt, Arabic Calligraphy Shirt")
        self.assertEqual(tags[:2], ["arabic shirt", "coffee shirt"])
        self.assertEqual(len(tags), 5)  # två egna och tre fyllnadstaggar; designerna har redan 13
        self.assertNotIn("mug", " ".join(tags))
        self.assertEqual(launch.adapt("Cozy Tee", ["cozy tee"], "hoodie")[0], "Cozy Hoodie")

    def test_a_second_run_updates_existing_products_instead_of_creating_duplicates(self):
        """Verifies D-070: pod prepare kan köras igen; finns produkten uppdateras bara titel, beskrivning och taggar."""
        first, _ = self.prepared()
        existing = {r.key: __import__("dataclasses").asdict(r) for r in first}
        fake = self.fake([900, 3_000])
        fake.routes[("PUT", "/v1/shops/5/products/p2.json")] = [(200, {}, None)]
        client = PrintifyClient("tok", transport=fake, min_interval=0)
        reader = PrintifyReader(self.system.engine, self.system.audit, "res-1", client)
        drafter = PrintifyDrafter(self.system.engine, self.system.audit, "lead-1", client, self.pod)
        again = launch.prepare(reader, drafter, 5, self.designs, self.pod, self.dir / "q4", existing)
        self.assertEqual([r.printify_id for r in again], ["p1", "p2"])
        self.assertFalse(any(c["method"] == "POST" for c in fake.calls))
        puts = [c["body"] for c in fake.calls if c["method"] == "PUT"]
        self.assertEqual(sorted(puts[0]), ["description", "tags", "title"])
        self.assertEqual(again[0].price_minor, first[0].price_minor)
