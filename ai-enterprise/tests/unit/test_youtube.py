"""YouTube Data API v3 som källa (Robin 2026-10-30): siffror i kod, kvot, nyckeln bara som rubrik."""
import json
import unittest
from datetime import date
from types import SimpleNamespace

from aie.pilot.discovery import Opportunity, run, score
from aie.research.youtube import YouTubeConfig, YouTubeSource, numbers
from aie.security.external import ExternalContent

from .test_discovery import FakeGateway, FakeReader, settings

SEARCH = {"items": [{"id": {"videoId": "v1"}}, {"id": {"videoId": "v2"}}]}
RECENT = {"pageInfo": {"totalResults": 312}}
VIDEOS = {"items": [
    {"id": "v1", "snippet": {"title": "Cinematic LUT pack for DaVinci Resolve", "publishedAt": "2026-08-01T00:00:00Z",
                             "description": "Get the pack for $19 at https://someone.gumroad.com/l/luts today"},
     "statistics": {"viewCount": "250000", "likeCount": "9000"}},
    {"id": "v2", "snippet": {"title": "Free LUTs", "publishedAt": "2025-01-01T00:00:00Z", "description": ""},
     "statistics": {"viewCount": "12000"}}]}


class FakeAPI:
    def __init__(self):
        self.calls = []

    def fetch(self, agent, url, secret_headers=None):
        self.calls.append((url, secret_headers))
        body = VIDEOS if "/videos?" in url else RECENT if "publishedAfter" in url else SEARCH
        return SimpleNamespace(fetch_id=len(self.calls), final_url=url,
                               content=ExternalContent(f"url:{url}", json.dumps(body)))


def source(api, queries=5, units=9000):
    return YouTubeSource(api, "scout-1", "SECRETKEY123456", YouTubeConfig(queries, units, 5, ("gumroad.com",)),
                         date(2026, 10, 30))


class TestYouTube(unittest.TestCase):
    def test_numbers_come_from_the_api_in_code(self):
        api = FakeAPI()
        signals = source(api).collect("davinci resolve luts", 1)
        n = numbers(signals)
        self.assertEqual((n["top_views"], n["new_videos_90d"]), (250000, 312))
        self.assertEqual(n["shop_prices_cents"], [1900])
        self.assertTrue(any("9000 gillamarkeringar" in s.title and "2026-08-01" in s.title for s in signals))
        self.assertTrue(all(h == {"X-goog-api-key": "SECRETKEY123456"} for _, h in api.calls))
        self.assertTrue(all("SECRETKEY" not in u for u, _ in api.calls))  # nyckeln aldrig i adressen
        self.assertIn("publishedAfter=2026-08-01", api.calls[1][0])

    def test_quota_is_respected(self):
        api = FakeAPI()
        yt = source(api, queries=1)
        yt.collect("a", 1)
        self.assertEqual(yt.collect("b", 10), [])
        self.assertEqual(len(api.calls), 3)
        self.assertIn("kvoten", yt.log[0])

    def test_only_relevant_youtube_numbers_qualify_an_idea(self):
        sig = {s.id: s for s in source(FakeAPI()).collect("davinci resolve luts", 1)}
        related = Opportunity("a", "DaVinci Resolve LUT pack", "lut", "gumroad", "english", "", 1900, 30, 0, 5, 14,
                              tuple(sig), "")
        unrelated = Opportunity("b", "Football tactics course", "course", "gumroad", "english", "", 1900, 30, 0,
                                5, 14, tuple(sig), "")
        self.assertTrue(score(related, sig, settings(), 500).qualified)
        self.assertFalse(score(unrelated, sig, settings(), 500).qualified)

    def test_7a_run_links_youtube_numbers_per_idea(self):
        class Both(FakeReader):
            def __init__(self):
                super().__init__()
                self.api = FakeAPI()

            def fetch(self, agent, url, secret_headers=None):
                return self.api.fetch(agent, url, secret_headers) if "googleapis" in url else super().fetch(agent, url)

        reader = Both()
        yt = YouTubeSource(reader, "res-1", "k" * 20, YouTubeConfig(20, 9000, 5, ("gumroad.com",)), date(2026, 10, 30))
        signals, ideas, top, log = run(reader, FakeGateway(), settings(), "regler", 500, yt, 1)
        self.assertTrue(any(s.count == 250000 for s in signals))
        self.assertTrue(top)


if __name__ == "__main__":
    unittest.main()
