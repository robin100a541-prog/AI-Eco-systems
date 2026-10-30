"""Fas 7a ombyggd (Robin 2026-10-30): research med källor, minst tio idéer, poäng i kod, ingen reserv."""
import json
import unittest
from types import SimpleNamespace

from aie.llm.providers import ChatResponse
from aie.pilot.discovery import Settings, report, run
from aie.pilot.product import AgentStopped
from aie.security.external import ExternalContent

PAGE = ("Cinematic LUT Pack for DaVinci Resolve $19 (1,240 ratings). Motion graphics transitions pack $25 "
        "sold 3,400 times. Question: how do I color grade football edits? " * 4)


def settings(**kw):
    base = dict(fees={"gumroad": {"percent_bp": 1000, "fixed_cents": 50}}, min_ideas=10, min_signals=2,
                min_expected_value_cents=15_000, max_fetches=2, search_urls=("https://gumroad.com/discover?query={q}",),
                skills=("davinci resolve", "motion graphics", "football"), languages=("english", "swedish"),
                audience=(), search_terms=("luts", "motion"))
    return Settings(**(base | kw))


class FakeReader:
    def __init__(self, text=PAGE, fail=False):
        self.text, self.fail, self.n = text, fail, 0

    def fetch(self, agent, url):
        if self.fail:
            raise ValueError("robots.txt tillåter inte hämtningen")
        self.n += 1
        return SimpleNamespace(fetch_id=self.n, final_url=url, content=ExternalContent(f"url:{url}", self.text))


def idea(n, sales=30, signals=("S1", "S2")):
    return {"id": f"idea-{n}", "title": f"DaVinci Resolve LUT pack {n}", "kind": "lut", "platform": "gumroad",
            "language": "english", "market": "global", "price_usd": 19, "est_sales_90d": sales,
            "upfront_cost_usd": 0, "hours_to_make": 10, "time_to_first_sale_days": 21,
            "signal_ids": list(signals), "reasoning": "motion graphics och football edits"}


class FakeGateway:
    def __init__(self, ideas=None, fake_quote=False, broken=False):
        self.ideas = ideas if ideas is not None else [idea(n) for n in range(10)]
        self.fake_quote, self.broken = fake_quote, broken

    def complete(self, agent, request):
        system = request.messages[0].content
        if self.broken:
            return ChatResponse("fake", "m", "inget json", 0)
        if "research-agenten" in system:
            quote = "this text is not on the page" if self.fake_quote else "Cinematic LUT Pack for DaVinci Resolve $19"
            sig = [{"kind": "competitor", "title": "LUT pack", "quote": quote, "price_usd": 19, "count": 1240},
                   {"kind": "question", "title": "football grading", "quote": "how do I color grade football edits?",
                    "price_usd": None, "count": None}]
            return ChatResponse("fake", "m", json.dumps({"signals": sig}), 0)
        return ChatResponse("fake", "m", json.dumps({"ideas": self.ideas}), 0)


class TestDiscovery(unittest.TestCase):
    def test_code_computes_money_scores_and_keeps_top_three_with_sources(self):
        signals, ideas, top, log = run(FakeReader(), FakeGateway(), settings(), "regler", 500)
        self.assertGreaterEqual(len(signals), 2)
        self.assertTrue(all(s.url.startswith("https://gumroad.com/") and s.fetch_id for s in signals))
        first = ideas[0]
        self.assertEqual((first.fee_cents, first.net_cents), (240, 1660))  # 10 % + 0,50 räknat i kod
        self.assertEqual(first.expected_value_cents, 30 * 1660)
        self.assertEqual(len(top), 3)
        text = report(signals, ideas, top, log, settings(), "fake")
        self.assertIn("## Topp 3", text)
        self.assertIn("https://gumroad.com/discover?query=luts", text)
        self.assertIn("Ingen vinnare är vald", text)

    def test_weak_ideas_give_no_good_idea_never_a_weak_pick(self):
        weak = [idea(n, sales=1) for n in range(10)]
        signals, ideas, top, log = run(FakeReader(), FakeGateway(ideas=weak), settings(), "regler", 500)
        self.assertEqual(top, [])
        self.assertIn("Ingen bra idé hittad ännu", report(signals, ideas, top, log, settings(), "fake"))

    def test_idea_needs_two_sourced_signals(self):
        one = [idea(n, signals=("S1",)) for n in range(10)]
        _, ideas, top, _ = run(FakeReader(), FakeGateway(ideas=one), settings(), "regler", 500)
        self.assertEqual(top, [])
        self.assertIn("1 belagda signaler", ideas[0].why_not[0])

    def test_invented_quotes_are_rejected_and_research_failure_stops(self):
        with self.assertRaises(AgentStopped):
            run(FakeReader(), FakeGateway(fake_quote=True), settings(max_fetches=1), "regler", 500)
        with self.assertRaises(AgentStopped):
            run(FakeReader(fail=True), FakeGateway(), settings(), "regler", 500)

    def test_model_failure_and_too_few_ideas_stop_without_fallback(self):
        with self.assertRaises(AgentStopped):
            run(FakeReader(), FakeGateway(broken=True), settings(), "regler", 500)
        with self.assertRaises(AgentStopped):
            run(FakeReader(), FakeGateway(ideas=[idea(1)]), settings(), "regler", 500)


if __name__ == "__main__":
    unittest.main()


class TestRepoConfig(unittest.TestCase):
    def test_repo_config_loads(self):
        from aie.pilot.discovery import load_settings

        from .fixture_config import ROOT
        s = load_settings(ROOT / "config")
        self.assertGreaterEqual(len(s.search_terms), 5)
        self.assertIn("gumroad", s.fees)
        self.assertEqual(s.min_signals, 2)


class TestRateLimit(unittest.TestCase):
    def test_429_is_retried_after_a_pause_not_replaced(self):
        from aie.pilot import discovery

        calls = []

        class Flaky(FakeGateway):
            def complete(self, agent, request):
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("groq: HTTP 429 (rate_limit_exceeded)")
                return super().complete(agent, request)

        waits = []
        old, discovery._sleep = discovery._sleep, waits.append
        try:
            run(FakeReader(), Flaky(), settings(), "regler", 500)
        finally:
            discovery._sleep = old
        self.assertEqual(waits, [20])
