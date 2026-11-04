"""Tester för Etsy-, Pinterest- och Instagram-klienterna och `aie connect` (arbetsorder 04, D-068, D-069).
Verifierar SR-02, SR-07 och SR-10. Allt nätverk är mockat; inga konton finns."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aie.authorization import PermissionDenied
from aie.config import load_config
from aie.memory import Database
from aie.pod import oauth
from aie.pod.channels import (ActionLog, EtsySignals, InstagramPublisher, PinterestPinner, PinterestTrends, Unavailable,
                              etsy_client, instagram_client, pinterest_client)
from aie.pod.printify import load_pod_config
from aie.simulation.agents import ensure_org
from aie.system import build_system

from .pod_helpers import FakeTransport, pod_config, tmpdir

ETSY_KEY = "keystring123:sharedsecret456"


class ChannelCase(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.config_dir = pod_config(self.dir)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.system = build_system(load_config(self.config_dir), self.db, self.config_dir)
        ensure_org(self.system.registry, "yorgo")
        self.pod = load_pod_config(self.config_dir)
        for service in ("etsy", "pinterest", "instagram"):
            self.pod[service]["enabled"] = True
        self.actions = ActionLog(self.db, clock=lambda: "2026-11-04")

    def args(self, agent="res-1"):
        return self.system.engine, self.system.audit, agent, self.pod


class TestDisabledByDefault(ChannelCase):
    def test_every_channel_is_off_in_the_repo_config_and_needs_its_key(self):
        """Verifies D-068: avstängt i pod.toml och utan nyckel används ingen klient."""
        repo = load_pod_config(self.config_dir)
        for service in ("etsy", "pinterest", "instagram"):
            self.assertFalse(repo[service]["enabled"])
        with self.assertRaisesRegex(Unavailable, "avstängt"):
            EtsySignals(self.system.engine, self.system.audit, "res-1", repo, etsy_client({"ETSY_API_KEY": ETSY_KEY}))
        with self.assertRaisesRegex(Unavailable, "shared secret"):
            etsy_client({"ETSY_API_KEY": "bara-keystring"})
        for factory in (pinterest_client, instagram_client):
            with self.assertRaises(Unavailable):
                factory(None)


class TestEtsy(ChannelCase):
    def test_search_sends_key_reads_signals_and_needs_the_tool(self):
        """Verifies D-068: x-api-key keystring:shared_secret, signaler för scouten, och verktyget krävs."""
        fake = FakeTransport({("GET", "/v3/application/listings/active"): [(200, {"count": 812, "results": [
            {"price": {"amount": 1899, "divisor": 100}, "num_favorers": 40},
            {"price": {"amount": 2499, "divisor": 100}, "num_favorers": 2}]}, None)]})
        etsy = EtsySignals(*self.args(), etsy_client({"ETSY_API_KEY": ETSY_KEY}, transport=fake))
        signal = etsy.search("christmas mug")
        self.assertEqual((signal["count"], signal["sampled"], signal["median_price"], signal["favorers"]),
                         (812, 2, 24.99, 42))
        self.assertEqual(fake.calls[0]["headers"]["x-api-key"], ETSY_KEY)
        self.assertIn("keywords=christmas+mug", fake.calls[0]["url"])
        with self.assertRaises(PermissionDenied):
            EtsySignals(*self.args("cfo-1"), etsy_client({"ETSY_API_KEY": ETSY_KEY}, transport=fake)).search("x")
        self.assertEqual(len(fake.calls), 1)


class TestPinterest(ChannelCase):
    def test_trends_use_the_documented_path_and_are_not_stored(self):
        """Verifies D-068: /v5/trends/keywords/{region}/top/{trend_type}; bara sökord och tillväxt returneras."""
        fake = FakeTransport({("GET", "/v5/trends/keywords/US/top/growing"): [
            (200, {"trends": [{"keyword": "cozy christmas", "pct_growth_wow": 30, "pct_growth_mom": 120,
                               "pct_growth_yoy": 15, "time_series": {"2026-11-01": 80}}]}, None)]})
        trends = PinterestTrends(*self.args(), pinterest_client("tok", transport=fake)).top("growing")
        self.assertEqual(trends, [{"keyword": "cozy christmas", "growth_wow": 30, "growth_mom": 120, "growth_yoy": 15}])
        for bad in (("weekly", "US"), ("growing", "USA")):
            with self.subTest(bad), self.assertRaises(ValueError):
                PinterestTrends(*self.args(), pinterest_client("tok", transport=fake)).top(*bad)

    def test_pins_link_only_to_etsy_and_stop_at_the_daily_limit(self):
        """Verifies D-069: bara länk till Etsy, högst max_pins_per_day; ett nej skickar inget."""
        self.pod["pinterest"]["max_pins_per_day"] = 2
        fake = FakeTransport({("POST", "/v5/pins"): [(201, {"id": "p1"}, None)]})
        pinner = PinterestPinner(*self.args("lead-1"), pinterest_client("tok", transport=fake), self.actions)
        with self.assertRaisesRegex(ValueError, "Etsy"):
            pinner.pin("b1", "t", "d", "https://evil.example/etsy.com", "https://img.example/a.jpg")
        for _ in range(2):
            pinner.pin("b1", "Cozy mug", "Original design", "https://www.etsy.com/listing/1", "https://img.example/a.jpg")
        with self.assertRaisesRegex(Unavailable, "gräns 2"):
            pinner.pin("b1", "Cozy mug", "d", "https://www.etsy.com/listing/1", "https://img.example/a.jpg")
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0]["body"]["media_source"], {"source_type": "image_url", "url": "https://img.example/a.jpg"})
        with self.assertRaises(PermissionDenied):
            PinterestPinner(*self.args("res-1"), pinterest_client("tok", transport=fake), self.actions).pin(
                "b1", "t", "d", "https://www.etsy.com/listing/1", "https://img.example/a.jpg")


class TestInstagram(ChannelCase):
    def test_carousel_jpeg_only_and_hard_cap_of_50(self):
        """Verifies D-069: container och publicering, bara JPEG, högst 20 bilder, aldrig fler än 50 per dygn."""
        fake = FakeTransport({("POST", "/v23.0/17841400000000000/media"): [(200, {"id": "c1"}, None)],
                              ("POST", "/v23.0/17841400000000000/media_publish"): [(200, {"id": "m1"}, None)]})
        self.pod["instagram"]["max_posts_per_day"] = 500  # en för hög egen gräns stoppas ändå vid 50
        ig = InstagramPublisher(*self.args("lead-1"), instagram_client("tok", transport=fake), self.actions,
                                "17841400000000000")
        self.assertEqual(ig.publish(["https://img.example/a.jpg", "https://img.example/b.jpeg"], "Original")["id"], "m1")
        self.assertEqual([c["path"].rsplit("/", 1)[1] for c in fake.calls], ["media", "media", "media", "media_publish"])
        self.assertEqual(fake.calls[2]["body"]["media_type"], "CAROUSEL")
        for bad in (["https://img.example/a.png"], ["http://img.example/a.jpg"], ["https://i/a.jpg"] * 21, []):
            with self.subTest(len(bad)), self.assertRaises(ValueError):
                ig.publish(bad, "x")
        for _ in range(49):
            self.actions.reserve("instagram", "post", "lead-1", "x", 50)
        with self.assertRaisesRegex(Unavailable, "gräns 50"):
            ig.publish(["https://img.example/a.jpg"], "x")


class TestConnect(unittest.TestCase):
    def test_pkce_matches_rfc_7636(self):
        """Verifies D-068: S256 enligt RFC 7636, bilaga B."""
        self.assertEqual(oauth.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
                         "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
        verifier, challenge = oauth.pkce_pair()
        self.assertTrue(43 <= len(verifier) <= 128)
        self.assertEqual(oauth.challenge(verifier), challenge)

    def test_state_is_checked_and_an_error_is_reported(self):
        """Verifies D-068: fel state eller ett nej från tjänsten avbryter flödet."""
        self.assertEqual(oauth.parse_redirect("https://x/cb?code=abc&state=s1", "s1"), "abc")
        for url in ("https://x/cb?code=abc&state=fel", "https://x/cb?error=access_denied&state=s1", "https://x/cb?state=s1"):
            with self.subTest(url), self.assertRaises(ValueError):
                oauth.parse_redirect(url, "s1")

    def test_etsy_flow_pastes_the_url_exchanges_with_pkce_and_saves_outside_the_repo(self):
        """Verifies SR-10: Etsy tar bara https, så adressen klistras in; token sparas med rättighet 600 utanför repot."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"ETSY_API_KEY": ETSY_KEY, "ETSY_REDIRECT_URI": "https://localhost:8765/callback"}
            fake = FakeTransport({("POST", "/v3/public/oauth/token"): [(200, {"access_token": "123.secret-token",
                                                                              "refresh_token": "r"}, None)]})
            opened, shown = [], []
            store = oauth.TokenStore(Path(tmp) / "tokens", environ={})

            def paste(prompt):
                query = oauth.urllib.parse.parse_qs(oauth.urllib.parse.urlsplit(opened[0]).query)
                return f"https://localhost:8765/callback?code=c0de&state={query['state'][0]}"

            with mock.patch("builtins.print", lambda *a, **k: shown.append(" ".join(map(str, a)))):
                path = oauth.connect("etsy", env, store=store, transport=fake, open_browser=opened.append,
                                     read_line=paste)
            query = oauth.urllib.parse.parse_qs(oauth.urllib.parse.urlsplit(opened[0]).query)
            self.assertEqual((query["client_id"][0], query["code_challenge_method"][0]), ("keystring123", "S256"))
            call = fake.calls[0]
            self.assertTrue(call["form"])
            self.assertEqual((call["body"]["code"], call["body"]["client_id"]), ("c0de", "keystring123"))
            self.assertEqual(oauth.challenge(call["body"]["code_verifier"]), query["code_challenge"][0])
            self.assertEqual(store.load("etsy")["access_token"], "123.secret-token")
            self.assertFalse(any("secret-token" in line or "sharedsecret456" in line for line in shown + opened))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_token_store_refuses_a_folder_inside_the_repo(self):
        """Verifies SR-10: token-filer kan aldrig hamna i repot."""
        with self.assertRaisesRegex(ValueError, "repot"):
            oauth.TokenStore(oauth.PROJECT_ROOT / "data" / "tokens")
        with self.assertRaisesRegex(ValueError, "saknas"):
            oauth.connect("pinterest", {"PINTEREST_APP_ID": "id"})
