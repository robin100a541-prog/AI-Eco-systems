"""Tester för Printify-klienten och verktygen printify.read och printify.draft (arbetsorder 04, D-065, D-069).
Verifierar SR-02, SR-07, SR-10 och D-008. Inga nätverksanrop."""
import unittest

from aie.authorization import PermissionDenied
from aie.config import load_config
from aie.memory import Database
from aie.pod import ApiError, JsonClient, PrintifyClient, PrintifyDrafter, PrintifyReader, RateLimited
from aie.pod.cli import catalog
from aie.pod.http import USER_AGENT
from aie.pod.printify import load_pod_config, parse_shipping
from aie.simulation.agents import ensure_org
from aie.system import build_system

from .pod_helpers import FakeTransport, pod_config, tmpdir

TOKEN = "pfy_test_" + "a" * 40  # inte en riktig nyckel
SHIPPING_V2 = {"data": [
    {"type": "shipping", "attributes": {"shippingType": "standard", "country": {"code": "US"}, "variantId": 1,
                                        "handlingTime": {"from": 2, "to": 5},
                                        "shippingCost": {"firstItem": {"amount": 399, "currency": "USD"},
                                                         "additionalItems": {"amount": 229, "currency": "USD"}}}},
    {"type": "shipping", "attributes": {"shippingType": "standard", "country": {"code": "REST_OF_THE_WORLD"},
                                        "variantId": 1, "handlingTime": {"from": 4, "to": 8},
                                        "shippingCost": {"firstItem": {"amount": 1099, "currency": "USD"}}}},
]}


class TestJsonClient(unittest.TestCase):
    def test_bearer_user_agent_timeout_and_https_only(self):
        """Verifies D-065: Bearer-token, egen User-Agent och tidsgräns; bara https mot den egna värden."""
        fake = FakeTransport({("GET", "/v1/shops.json"): [(200, [{"id": 1}], None)]})
        client = PrintifyClient(TOKEN, transport=fake, timeout=12, min_interval=0)
        self.assertEqual(client.get("/v1/shops.json"), [{"id": 1}])
        call = fake.calls[0]
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(call["headers"]["User-Agent"], USER_AGENT)
        self.assertEqual(call["timeout"], 12)
        with self.assertRaises(ValueError):
            JsonClient("http://api.printify.com", {})
        for bad in ("//evil.example/x", "/../x", "v1/shops"):
            with self.subTest(bad), self.assertRaises(ValueError):
                client.get(bad)

    def test_429_respects_retry_after_and_gives_up_after_the_limit(self):
        """Verifies D-065: begränsade återförsök; Retry-After följs; efter sista försöket kastas RateLimited."""
        slept = []
        fake = FakeTransport({("GET", "/v1/shops.json"): [(429, None, {"Retry-After": "7"}), (200, [], None)]})
        client = PrintifyClient(TOKEN, transport=fake, min_interval=0, sleep=slept.append)
        self.assertEqual(client.get("/v1/shops.json"), [])
        self.assertEqual(slept, [7.0])
        fake = FakeTransport({("GET", "/v1/shops.json"): [(429, None, {})]})
        client = PrintifyClient(TOKEN, transport=fake, min_interval=0, retries=2, sleep=lambda s: None)
        with self.assertRaises(RateLimited):
            client.get("/v1/shops.json")
        self.assertEqual(len(fake.calls), 3)

    def test_the_token_never_appears_in_errors_or_repr(self):
        """Verifies SR-10: ett fel som ekar nyckeln maskeras, och repr visar ingen nyckel."""
        fake = FakeTransport({("GET", "/v1/shops.json"): [(401, {"error": f"bad token {TOKEN}"}, None)]})
        client = PrintifyClient(TOKEN, transport=fake, min_interval=0)
        with self.assertRaises(ApiError) as ctx:
            client.get("/v1/shops.json")
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertNotIn(TOKEN, repr(client) + repr(client._http))
        with self.assertRaisesRegex(ApiError, "PRINTIFY_API_TOKEN saknas"):
            PrintifyClient.from_env({})

    def test_the_client_can_never_publish(self):
        """Verifies D-069: publicering finns inte i klienten."""
        client = PrintifyClient(TOKEN, transport=FakeTransport(), min_interval=0)
        with self.assertRaises(ValueError):
            client.post("/v1/shops/1/products/2/publish.json", {})


class TestShipping(unittest.TestCase):
    def test_v2_shipping_is_parsed_in_cents_per_country(self):
        """Verifies D-066: frakten i cent per land, med REST_OF_THE_WORLD som reserv."""
        rows = parse_shipping(SHIPPING_V2)
        self.assertEqual((rows[0]["country"], rows[0]["first_item_minor"], rows[0]["handling_days"]), ("US", 399, (2, 5)))
        self.assertEqual(rows[1]["country"], "REST_OF_THE_WORLD")


class SystemCase(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.config_dir = pod_config(self.dir)
        self.config = load_config(self.config_dir)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.system = build_system(self.config, self.db, self.config_dir)
        ensure_org(self.system.registry, "yorgo")
        self.pod = load_pod_config(self.config_dir)

    def reader(self, fake, agent="res-1"):
        return PrintifyReader(self.system.engine, self.system.audit, agent,
                              PrintifyClient(TOKEN, transport=fake, min_interval=0))


class TestRead(SystemCase):
    def test_read_needs_the_tool_and_stops_before_any_http_call(self):
        """Verifies SR-02 och SR-07: en roll utan printify.read, och nödstoppet, stoppar före anropet."""
        fake = FakeTransport({("GET", "/v1/shops.json"): [(200, [], None)]})
        with self.assertRaises(PermissionDenied):
            self.reader(fake, agent="cfo-1").shops()
        self.system.kill.engage("cro-1", "test")
        with self.assertRaises(PermissionDenied):
            self.reader(fake).shops()
        self.assertEqual(fake.calls, [])

    def test_daily_catalog_snapshot_has_variants_and_shipping_and_logs_without_token(self):
        """Verifies D-065 och D-066: katalog, sökord, varianter och frakt per land; loggen saknar nyckel."""
        fake = FakeTransport({
            ("GET", "/v1/catalog/blueprints.json"): [(200, [{"id": 6, "title": "Unisex Heavy Cotton Tee"},
                                                           {"id": 68, "title": "Ceramic Mug 11oz"}], None)],
            ("GET", "/v1/catalog/blueprints/6/print_providers.json"): [(200, [{"id": 99, "title": "P"}], None)],
            ("GET", "/v1/catalog/blueprints/6/print_providers/99/variants.json"):
                [(200, {"variants": [{"id": 1, "title": "Black / M"}]}, None)],
            ("GET", "/v2/catalog/blueprints/6/print_providers/99/shipping/standard.json"): [(200, SHIPPING_V2, None)],
        })
        self.pod["printify"]["q4_search"] = ["heavy cotton tee"]
        result = catalog(self.reader(fake), self.pod)
        self.assertEqual(result["blueprints"], 2)
        (snap,) = result["snapshots"]
        self.assertEqual(snap["title"], "Unisex Heavy Cotton Tee")
        self.assertEqual(snap["variants"], [{"id": 1, "title": "Black / M", "cost_minor": None}])
        self.assertEqual(snap["shipping_standard"]["US"]["first_item_minor_max"], 399)
        self.assertTrue(snap["shipping_standard"]["SE"]["fallback"])
        self.assertTrue(all(c["method"] == "GET" for c in fake.calls))
        logged = [e for e in self.system.audit.entries() if e.action == "printify.read"]
        self.assertEqual(len(logged), 4)
        self.assertFalse(any(TOKEN in str(e.details) for e in self.system.audit.entries()))


class TestDraft(SystemCase):
    def drafter(self, fake, enabled, rules=None):
        self.pod["printify"]["draft_enabled"] = enabled
        return PrintifyDrafter(self.system.engine, self.system.audit, "lead-1",
                               PrintifyClient(TOKEN, transport=fake, min_interval=0), self.pod, rules)

    def test_draft_is_off_until_the_decision_and_then_needs_the_tool(self):
        """Verifies D-069: avstängt i pod.toml; påslaget krävs ändå printify.draft; inget anrop vid nej."""
        fake = FakeTransport({("POST", "/v1/shops/5/products.json"): [(200, {"id": "p1"}, None)]})
        with self.assertRaisesRegex(PermissionError, "avstängt"):
            self.drafter(fake, False).create_draft(5, {"title": "x"})
        self.assertTrue(load_pod_config(self.config_dir)["printify"]["draft_enabled"])  # påslaget av Yorgo 2026-11-04 (LANSERING-Q4)
        self.assertEqual(self.drafter(fake, True).create_draft(5, {"title": "Vinterljus"})["id"], "p1")
        with self.assertRaises(PermissionDenied):
            PrintifyDrafter(self.system.engine, self.system.audit, "res-1",
                            PrintifyClient(TOKEN, transport=fake, min_interval=0), self.pod).create_draft(5, {})
        self.assertEqual([c["path"] for c in fake.calls], ["/v1/shops/5/products.json"])

    def test_rules_stop_a_draft_and_only_png_or_jpeg_is_uploaded(self):
        """Verifies D-067: en produkt som bryter mot reglerna skapas inte; SVG laddas inte upp."""
        fake = FakeTransport()
        drafter = self.drafter(fake, True, rules=lambda p: ["varumärke"] if "Disney" in p["title"] else [])
        with self.assertRaisesRegex(ValueError, "varumärke"):
            drafter.create_draft(5, {"title": "Disney jul"})
        with self.assertRaisesRegex(ValueError, "PNG och JPEG"):
            drafter.upload_image("design.svg", "https://example.com/design.svg")
        self.assertEqual(fake.calls, [])
