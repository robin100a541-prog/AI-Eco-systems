"""Tester för annons- och motivreglerna (arbetsorder 04, D-067). Verifierar att egna motiv krävs och att Etsys
krav på produktionspartner och AI-upplysning kontrolleras i koden."""
import unittest
from pathlib import Path

from aie.pod.printify import load_pod_config
from aie.pod.rules import design_problems, listing_problems, load_blocklist

CONFIG = Path(__file__).resolve().parents[2] / "config"
GOOD = {"title": "Cozy Winter Nights Typography Mug, Minimalist Holiday Gift", "tags": ["winter mug", "holiday gift"],
        "description": "Original typography design. Made with the help of AI and finished by hand.",
        "production_partners": ["Printify"], "design_text": "COZY WINTER NIGHTS"}


class TestRules(unittest.TestCase):
    def setUp(self):
        self.rules = load_pod_config(CONFIG)["etsy"]["listing_rules"]
        self.blocklist = load_blocklist(CONFIG)

    def test_an_own_design_with_partner_and_ai_disclosure_passes(self):
        """Verifies D-067: en egen typografisk design med Printify och AI-upplysning går igenom."""
        self.assertEqual(listing_problems(GOOD, self.rules, self.blocklist), [])

    def test_trademarks_people_and_copy_phrases_are_stopped(self):
        """Verifies D-067: varumärken, kända personer, kopiering och skyddsmärken stoppas, oavsett skiftläge och accent."""
        for text in ("grinch christmas sweater", "POKÉMON gift", "Taylor Swift era mug", "in the style of Van Gogh",
                     "Moomin mug", "Holiday Cheer™"):
            with self.subTest(text):
                self.assertTrue(design_problems(text, self.blocklist))
        for text in ("self care gift", "marvelous winter nights"):  # hela ord: "elf" och "marvel" finns inuti
            with self.subTest(text):
                self.assertEqual(design_problems(text, self.blocklist), [])
        # "Frozen" är spärrat som helt ord, även i en oskyldig titel: hellre ett falskt stopp än ett intrång
        self.assertTrue(design_problems("frozen lake typography", self.blocklist))

    def test_missing_partner_ai_text_and_etsy_limits_are_reported(self):
        """Verifies D-067: Etsy kräver produktionspartner och AI-upplysning; titel och taggar har gränser."""
        bad = dict(GOOD, production_partners=[], description="Original design.", title="x" * 141,
                   tags=[f"tag{i}" for i in range(14)] + ["a" * 21])
        problems = " | ".join(listing_problems(bad, self.rules, self.blocklist))
        for expected in ("produktionspartner", "AI-användningen", "141 tecken", "15 taggar", "över 20 tecken"):
            self.assertIn(expected, problems)
