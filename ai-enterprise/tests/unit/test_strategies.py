"""Tester för versionerade strategier (Fas 5e). Verifierar FR-18, FR-17, §30 och §53."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import load_permissions
from aie.evaluation import LessonRegistry, StrategyError, StrategyRegistry
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"robin", "yorgo"})
V1 = {"pris": 49, "kanal": "etsy"}
V2 = {"pris": 79, "kanal": "etsy", "rabatt": 10}


class StrategyCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.start()
        self.add("ceo-1", "ceo")
        self.add("lead-1", "research_lead", "ceo-1")
        self.add("res-1", "researcher", "lead-1")

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.lessons = LessonRegistry(self.db, self.registry, self.permissions, self.audit, FOUNDERS)
        self.strategies = StrategyRegistry(self.db, self.registry, self.permissions, self.audit, FOUNDERS, self.lessons)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def rule(self):
        lid = self.lessons.propose("res-1", "högre pris säljer lika bra", "bad_strategy", "research",
                                   ("test:a",)).lesson_id
        self.lessons.promote("lead-1", lid, "rimlig")
        self.lessons.promote("lead-1", lid, "ett test")
        self.lessons.add_evidence("res-1", lid, ("test:b",), "igen")
        self.lessons.promote("lead-1", lid, "två test")
        self.lessons.vote_rule("robin", lid, "ok")
        self.lessons.vote_rule("yorgo", lid, "ok")
        return lid


class TestVersions(StrategyCase):
    def test_versions_are_numbered_and_the_latest_applies(self):
        """Verifies FR-18: varje ändring är en ny numrerad version; den senaste gäller; diff visar ändringen."""
        self.strategies.save("lead-1", "etsy-pris", V1, "start")
        v2 = self.strategies.save("lead-1", "etsy-pris", V2, "test visade högre betalningsvilja")
        self.assertEqual((v2.version, self.strategies.active("etsy-pris").content), (2, V2))
        self.assertEqual(self.strategies.diff("etsy-pris", 1, 2), {"pris": (49, 79), "rabatt": (None, 10)})
        with self.assertRaises(StrategyError):
            self.strategies.save("lead-1", "etsy-pris", V2, "samma igen")

    def test_restore_is_a_new_version_and_history_stays(self):
        """Verifies FR-18 och §53: en strategiförändring kan återställas; återställningen är en ny version."""
        self.strategies.save("lead-1", "etsy-pris", V1, "start")
        self.strategies.save("lead-1", "etsy-pris", V2, "höjt pris")
        v3 = self.strategies.restore("robin", "etsy-pris", 1, "försäljningen föll")
        self.assertEqual((v3.version, v3.content, v3.restores), (3, V1, self.strategies.get("etsy-pris", 1).version_id))
        self.assertEqual([v.version for v in self.strategies.history("etsy-pris")], [1, 2, 3])
        with self.assertRaises(StrategyError):
            self.strategies.restore("robin", "etsy-pris", 3, "redan gällande")
        for sql in ("UPDATE strategy_versions SET content = '{}'", "DELETE FROM strategy_versions"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)
        self.db.close()
        self.start()
        self.assertEqual(self.strategies.active("etsy-pris").content, V1)  # FR-03

    def test_agent_versions(self):
        """Verifies FR-18: agentversioner versionshanteras och kan återställas; agenten måste finnas."""
        self.strategies.save("robin", "agent:res-1", {"modell": "llama3", "instruktion": "v1"}, "start")
        self.strategies.save("robin", "agent:res-1", {"modell": "qwen", "instruktion": "v2"}, "bättre svar")
        self.assertEqual(self.strategies.restore("yorgo", "agent:res-1", 1, "regression").content["modell"], "llama3")
        self.assertEqual(self.strategies.history("agent:res-1")[0].kind, "agent")
        with self.assertRaises(StrategyError):
            self.strategies.save("robin", "agent:ghost", {"modell": "x"}, "start")


class TestMandatory(StrategyCase):
    def test_mandatory_change_needs_an_operational_rule_and_a_founder(self):
        """Verifies FR-17 och §53: bara godkända operativa regler får göra en ändring obligatorisk."""
        hypothesis = self.lessons.propose("res-1", "kanske", "random", "research", ("test:x",)).lesson_id
        for author, lessons in (("robin", ()), ("robin", (hypothesis,)), ("lead-1", (self.rule(),))):
            with self.subTest(author=author, lessons=lessons), self.assertRaises(StrategyError):
                self.strategies.save(author, "gemensam-prisregel", V2, "regel", lessons, mandatory=True)
        rule = self.lessons.rules()[0].lesson_id
        v = self.strategies.save("robin", "gemensam-prisregel", V2, "regel", (rule,), mandatory=True)
        self.assertEqual((v.mandatory, v.unverified_lessons), (True, ()))

    def test_ordinary_change_may_cite_unverified_lessons_but_they_are_marked(self):
        """Verifies FR-17: en vanlig ändring får hänvisa till en hypotes, men den markeras som ej verifierad."""
        hypothesis = self.lessons.propose("res-1", "kanske", "random", "research", ("test:x",)).lesson_id
        v = self.strategies.save("lead-1", "etsy-pris", V1, "experiment", (hypothesis,))
        self.assertEqual(v.unverified_lessons, (hypothesis,))
        with self.assertRaises(StrategyError):
            self.strategies.save("res-1", "etsy-pris", V2, "arbetsagenter ändrar inte strategier")


if __name__ == "__main__":
    unittest.main()
