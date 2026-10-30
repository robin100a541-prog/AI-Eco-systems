"""Tester för samråd (Fas 3c). Verifierar FR-11, FR-03 och ER-02."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import load_permissions
from aie.collaboration import (
    ConsultationBoard,
    ConsultationError,
    Position,
    RiskClass,
    required_for,
)
from aie.config import Money
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
S, P, R = AgentState, Position, RiskClass
FOUNDERS = frozenset({"yorgo", "robin"})
THRESHOLD = Money(10_000, "SIM")


def sim(amount):
    return Money(amount, "SIM")


class TestRequiredRoles(unittest.TestCase):
    def test_amount_needs_cfo_and_risk_needs_cro_and_legal_needs_compliance(self):
        """Verifies FR-11: belopp kräver CFO, risk kräver CRO och juridik kräver Compliance."""
        self.assertEqual(required_for(sim(500), R.LOW, False, THRESHOLD).roles, ("cfo",))
        self.assertEqual(required_for(None, R.HIGH, False, THRESHOLD).roles, ("cro",))
        self.assertEqual(required_for(None, R.LOW, True, THRESHOLD).roles, ("compliance",))
        self.assertEqual(required_for(sim(500), R.MEDIUM, True, THRESHOLD).roles, ("cfo", "cro", "compliance"))

    def test_founders_above_threshold_critical_or_missing_limit(self):
        """Verifies FR-11, D-019 och ER-02: över gränsen, kritisk risk eller saknad gräns kräver grundarna."""
        self.assertFalse(required_for(sim(10_000), R.LOW, False, THRESHOLD).requires_founders)
        self.assertTrue(required_for(sim(10_001), R.LOW, False, THRESHOLD).requires_founders)
        self.assertTrue(required_for(None, R.CRITICAL, False, THRESHOLD).requires_founders)
        self.assertTrue(required_for(sim(1), R.LOW, False, None).requires_founders)

    def test_nothing_needed_for_low_risk_without_amount(self):
        """Verifies FR-11: låg risk utan belopp och utan juridik kräver inget samråd."""
        req = required_for(None, R.LOW, False, THRESHOLD)
        self.assertEqual((req.roles, req.requires_founders), ((), False))


class BoardCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.start()
        self.add("ceo-1", "ceo")
        for agent_id, role in (("cfo-1", "cfo"), ("cro-1", "cro"), ("comp-1", "compliance"), ("audit-1", "auditor")):
            self.add(agent_id, role)
        self.add("lead-1", "research_lead", "ceo-1")
        self.add("res-1", "researcher", "lead-1")

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.board = ConsultationBoard(self.db, self.registry, self.permissions, self.audit, FOUNDERS, THRESHOLD)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def investment(self, amount=5_000, risk=R.MEDIUM, legal=False):
        return self.board.open("ceo-1", "task:7", "Köpa mallpaket för Gumroad?", risk, sim(amount), legal)


class TestFlow(BoardCase):
    def test_consultation_completes_when_all_required_roles_answer(self):
        """Verifies FR-11: samrådet är klart först när CFO och CRO båda har yttrat sig."""
        c = self.investment()
        self.assertEqual(c.required_roles, ("cfo", "cro"))
        c = self.board.respond("cfo-1", c.consultation_id, P.SUPPORT, "ryms i budget", ("ledger:3",))
        self.assertFalse(c.complete)
        self.assertEqual(c.missing_roles, ("cro",))
        c = self.board.respond("cro-1", c.consultation_id, P.SUPPORT, "måttlig risk, liten förlust möjlig")
        self.assertTrue(c.complete)
        self.assertTrue(c.unanimous)
        actions = [e.action for e in self.audit.entries()]
        self.assertEqual(actions.count("consultation.opinion"), 2)
        self.assertTrue(self.audit.verify().ok)

    def test_disagreement_is_kept_not_voted_away(self):
        """Verifies FR-11 (§20): samråd kräver inte enighet; invändningen finns kvar med sitt underlag."""
        c = self.investment(legal=True)
        self.board.respond("cfo-1", c.consultation_id, P.SUPPORT, "lönsamt enligt kalkyl", ("file:kalkyl.csv",))
        self.board.respond("cro-1", c.consultation_id, P.SUPPORT, "acceptabel risk")
        c = self.board.respond("comp-1", c.consultation_id, P.OBJECT, "licensen tillåter inte vidareförsäljning",
                               ("url:https://example.com/license",))
        self.assertTrue(c.complete)
        self.assertFalse(c.unanimous)
        self.assertEqual([o.role for o in c.objections], ["compliance"])

    def test_above_threshold_flags_founders(self):
        """Verifies D-019: ett belopp över HUMAN_APPROVAL_THRESHOLD markerar att grundarna måste besluta."""
        self.assertTrue(self.investment(amount=50_000).requires_founders)
        self.assertFalse(self.investment(amount=5_000).requires_founders)

    def test_survives_restart(self):
        """Verifies FR-03: samråd och yttranden finns kvar efter omstart."""
        c = self.investment()
        self.board.respond("cfo-1", c.consultation_id, P.ABSTAIN, "saknar underlag om leverantören")
        self.db.close()
        self.start()
        c = self.board.get(c.consultation_id)
        self.assertEqual((c.amount, c.missing_roles, c.opinions[0].position), (sim(5_000), ("cro",), P.ABSTAIN))


class TestRules(BoardCase):
    def test_only_levels_1_to_3_or_founders_open(self):
        """Verifies FR-11: en arbetsagent kan inte öppna samråd; grundare, CEO, kontroll och chefer kan."""
        with self.assertRaises(ConsultationError):
            self.board.open("res-1", "task:1", "x", R.HIGH)
        for actor in ("yorgo", "ceo-1", "cro-1", "lead-1"):
            with self.subTest(actor=actor):
                self.assertIsNotNone(self.board.open(actor, "task:1", "x", R.HIGH))

    def test_only_required_role_answers_once(self):
        """Verifies FR-11: bara krävda roller yttrar sig, en gång var, och yttrandet ändras aldrig."""
        c = self.investment()
        for agent_id in ("audit-1", "comp-1", "ceo-1"):
            with self.subTest(agent=agent_id), self.assertRaises(ConsultationError):
                self.board.respond(agent_id, c.consultation_id, P.SUPPORT, "vill vara med")
        self.board.respond("cfo-1", c.consultation_id, P.SUPPORT, "ok")
        with self.assertRaises(ConsultationError):
            self.board.respond("cfo-1", c.consultation_id, P.OBJECT, "ändrat mig", ("ledger:1",))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute("UPDATE consultation_opinions SET position = 'object'")

    def test_opinion_needs_reasoning_and_objection_needs_evidence(self):
        """Verifies FR-11 (§20 steg 5, §21): varje yttrande har motivering och en invändning har underlag."""
        c = self.investment()
        with self.assertRaises(ConsultationError):
            self.board.respond("cfo-1", c.consultation_id, P.SUPPORT, " ")
        with self.assertRaises(ConsultationError):
            self.board.respond("cfo-1", c.consultation_id, P.OBJECT, "för dyrt")
        with self.assertRaises(ConsultationError):
            self.board.respond("cfo-1", c.consultation_id, P.OBJECT, "för dyrt", ("lita på mig",))

    def test_suspended_role_cannot_answer(self):
        """Verifies FR-11: en avstängd CFO kan inte yttra sig."""
        c = self.investment()
        self.registry.transition("cfo-1", S.SUSPENDED, "yorgo", "test")
        with self.assertRaises(ConsultationError):
            self.board.respond("cfo-1", c.consultation_id, P.SUPPORT, "ok")

    def test_invalid_openings(self):
        """Verifies FR-11 och ER-15: fel valuta, negativt belopp, tomt ämne och onödigt samråd avvisas."""
        for kwargs in (
            {"amount": Money(1, "SEK")},
            {"amount": sim(-1)},
            {"subject": " "},
            {"risk": R.LOW},
        ):
            args = {"actor": "ceo-1", "subject": "task:1", "question": "x", "risk_class": R.MEDIUM}
            if "risk" in kwargs:
                args["risk_class"] = kwargs.pop("risk")
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ConsultationError):
                self.board.open(**args)

    def test_database_blocks_edit_and_delete(self):
        """Verifies FR-11: samråd och yttranden kan inte ändras eller raderas, inte ens med SQL."""
        c = self.investment()
        self.board.respond("cfo-1", c.consultation_id, P.SUPPORT, "ok")
        for sql in ("UPDATE consultations SET required_roles = '[]'", "DELETE FROM consultations",
                    "DELETE FROM consultation_opinions"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)


if __name__ == "__main__":
    unittest.main()
