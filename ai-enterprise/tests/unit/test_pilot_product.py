"""Fas 7a/7c: produktagenten och beslutscykeln med en falsk modell. Verifierar §20 steg 7, §21 och D-063."""
import json
import tempfile
import unittest
from pathlib import Path

from aie.config import load_config
from aie.governance import Decision
from aie.governance.cli import build
from aie.llm import LLMGateway
from aie.llm.providers import RuleProvider
from aie.llm.router import ProviderRouter, QuotaLedger, Slot
from aie.memory import Database
from aie.pilot.decide import CEO, run_cycle, should_object
import json

from aie.pilot.product import AgentStopped, IdeaError, parse_idea, propose
from aie.pilot.writer import AI_DISCLOSURE, listing, write_product
from aie.simulation.agents import ensure_org

from .fixture_config import TEST_CONFIG

RULE_IDEAS = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "rule_ideas.json").read_text())
IDEAS = [dict(r) for r in RULE_IDEAS]


class FakeModel:
    """Svarar som en modell: förslag, bedömningar och CEO-beslut. Kan göras felaktig per roll."""

    def __init__(self, ideas=IDEAS, cro_objects=(), ceo=None):
        self.ideas, self.cro_objects, self.ceo = ideas, set(cro_objects), ceo

    def __call__(self, request):
        text = request.messages[0].content
        if "produktagenten" in text:
            return json.dumps({"ideas": self.ideas})
        if text.startswith("Du är CFO"):
            return json.dumps({"assessments": [{"idea_id": i["id"], "position": "for", "reason": "lönsam"}
                                               for i in self.ideas]})
        if text.startswith("Du är Riskchef"):
            return json.dumps({"assessments": [
                {"idea_id": i["id"], "position": "against" if i["id"] in self.cro_objects else "for",
                 "reason": "bedömd"} for i in self.ideas]})
        if text.startswith("Du är CEO"):
            return json.dumps(self.ceo or {
                "idea_id": "frilans-fakturamall", "chosen_action": "välj fakturamallen", "reasoning": "bäst netto",
                "evidence": ["förslaget"], "budget_minor": 0, "risk_class": "low", "expected_result": "10 st",
                "stop_conditions": "ingen försäljning på 60 dagar", "follow_up": "varje vecka",
                "expected_net_90d_usd": 76.0})
        return "# Produkt\n" + "Innehåll. " * 300


class PilotCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config = load_config(TEST_CONFIG)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.gov = build(self.config, self.db, TEST_CONFIG)
        ensure_org(self.gov.registry, "robin")

    def gateway(self, model):
        slots = (Slot(RuleProvider("fake", model), 1_000, 10_000_000),)
        return LLMGateway(ProviderRouter(slots, QuotaLedger(self.db), self.gov.audit), self.gov.engine, self.gov.audit)

    def cycle(self, model, ideas=None):
        gw = self.gateway(model)
        ideas = ideas or propose(gw)[0]
        return run_cycle(self.gov, gw, ideas, "robin", self.config.risk, 10.5), ideas


class TestProductAgent(PilotCase):
    def test_model_ideas_are_validated_and_fees_computed_in_code(self):
        ideas, log = propose(self.gateway(FakeModel()))
        self.assertEqual(log["source"], "model")
        first = ideas[0]
        self.assertEqual(first.fee_cents, 140)  # 10 % av 9 USD + 0,50 USD
        self.assertEqual(first.net_per_sale_cents, 760)
        self.assertTrue(all(i.demand_status == "unverified" for i in ideas))

    def test_model_sums_are_ignored_so_rounding_never_rejects(self):
        """Robin 2026-10-30: koden räknar; modellens summor används aldrig."""
        odd = [dict(i, expected_net_90d_usd=9999) for i in IDEAS]
        ideas, log = propose(self.gateway(FakeModel(ideas=odd)))
        self.assertEqual(log["source"], "model")
        self.assertEqual(ideas[0].net_per_sale_cents, 760)

    def test_no_fallback_when_model_fails(self):
        with self.assertRaises(AgentStopped):
            propose(self.gateway(lambda req: "inget json"))
    def test_missing_fields_are_rejected(self):
        with self.assertRaises(IdeaError):
            parse_idea({"id": "x-y-z", "title": "t"})


class TestDecisionCycle(PilotCase):
    def test_valid_model_decision_is_recorded_with_all_fields(self):
        result, _ = self.cycle(FakeModel())
        self.assertIsInstance(result.decision, Decision)
        self.assertEqual(result.chosen.id, "frilans-fakturamall")
        self.assertTrue(all(r["valid"] for r in result.quality["roles"].values()))

    def test_budget_comes_from_code_not_model(self):
        ceo = {"idea_id": "frilans-fakturamall", "chosen_action": "a", "reasoning": "b", "evidence": ["c"],
               "budget_minor": 12345, "risk_class": "low", "expected_result": "d", "stop_conditions": "e",
               "follow_up": "f"}
        result, _ = self.cycle(FakeModel(ceo=ceo))
        self.assertEqual(result.decision.budget_minor, 0)
    def test_choosing_an_objected_idea_stops_without_fallback(self):
        with self.assertRaises(AgentStopped):
            self.cycle(FakeModel(cro_objects={"frilans-fakturamall"}))
    def test_unknown_choice_stops_without_fallback(self):
        risky = parse_idea(dict(IDEAS[0], id="dyr-kurs", upfront_costs_usd=50))
        self.assertTrue(should_object(risky, self.config.risk, 10.5))
        with self.assertRaises(AgentStopped):
            self.cycle(FakeModel(), (risky,))

class TestWriter(unittest.TestCase):
    def test_files_and_pdf(self):
        idea = parse_idea(IDEAS[0])
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_product(idea, "# Titel\nÅÄÖ (test)\n", "rule", Path(tmp))
            pdf = (folder / "product.pdf").read_bytes()
            self.assertTrue(pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF"))
            self.assertIn(b"\xc5\xc4\xd6", pdf)  # ÅÄÖ i WinAnsi
            self.assertEqual(json.loads((folder / "idea.json").read_text())["fee_cents"], 140)
        self.assertIn(AI_DISCLOSURE, listing(idea))
        self.assertIn("OVERIFIERAD", listing(idea))


if __name__ == "__main__":
    unittest.main()
