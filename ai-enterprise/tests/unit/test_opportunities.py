"""Tester för "Utred möjlighet" (Fas 3i). Verifierar FR-25, D-011, §17, §29 och FR-03."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import load_permissions
from aie.collaboration import OpportunityError, OpportunityRegister
from aie.config import Money
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"yorgo", "robin"})
ETSY = ("url:https://www.etsy.com/legal/creativity",)


class OpportunityCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.start()
        self.add("ceo-1", "ceo")
        for agent_id, role in (("cfo-1", "cfo"), ("comp-1", "compliance")):
            self.add(agent_id, role)
        self.add("lead-1", "research_lead", "ceo-1")
        self.add("res-1", "researcher", "lead-1")

    def start(self):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.reg = OpportunityRegister(self.db, self.registry, self.permissions, self.audit, FOUNDERS)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def through_cfo(self, kind="channel", ref="R-04"):
        o = self.reg.open("lead-1", kind, "Gumroad som kanal", "Vilka regler gäller för AI-produkter?", ref)
        o = self.reg.submit_findings("res-1", o.opportunity_id, "AI tillåtet om det anges", ETSY)
        o = self.reg.compliance_review("comp-1", o.opportunity_id, "ok", "villkoren uppfylls om AI anges")
        return self.reg.cfo_estimate("cfo-1", o.opportunity_id, "netto efter 10 % + 0,50 USD", Money(42_000, "SIM"))


class TestFlow(OpportunityCase):
    def test_full_flow_research_compliance_cfo_founders(self):
        """Verifies FR-25 (D-011): Research → Compliance → CFO → grundare, med status som i QUESTIONS.md."""
        o = self.reg.open("lead-1", "channel", "Gumroad", "Får vi sälja AI-mallar?", "R-04")
        self.assertEqual((o.stage, o.status), ("research", "open"))
        o = self.reg.submit_findings("res-1", o.opportunity_id, "AI tillåtet om det anges", ETSY)
        self.assertEqual((o.stage, o.status), ("compliance", "unconfirmed_hypothesis"))  # §29
        o = self.reg.compliance_review("comp-1", o.opportunity_id, "ok", "villkor OK")
        self.assertEqual((o.stage, o.status), ("cfo", "verified"))
        o = self.reg.cfo_estimate("cfo-1", o.opportunity_id, "netto", Money(42_000, "SIM"))
        self.assertEqual(o.stage, "founders")
        o = self.reg.founder_decision("robin", o.opportunity_id, True, "provas i pilot")
        self.assertEqual((o.stage, o.status), ("closed", "approved"))
        self.assertEqual([s.verdict for s in o.steps], ["findings", "ok", "estimate", "approve"])
        self.assertEqual(o.steps[2].net, Money(42_000, "SIM"))
        self.assertEqual(o.sources, ETSY)
        self.assertTrue(self.audit.verify().ok)

    def test_order_cannot_be_skipped(self):
        """Verifies FR-25: varje steg måste ske i ordning; CFO och grundare kan inte hoppa före Compliance."""
        o = self.reg.open("lead-1", "tool", "Ollama", "Kan vi köra lokalt?")
        with self.assertRaises(OpportunityError):
            self.reg.compliance_review("comp-1", o.opportunity_id, "ok", "x")
        self.reg.submit_findings("res-1", o.opportunity_id, "MIT-licens", ("url:https://ollama.com",))
        for call in (lambda: self.reg.cfo_estimate("cfo-1", o.opportunity_id, "x", Money(1, "SIM")),
                     lambda: self.reg.founder_decision("yorgo", o.opportunity_id, True, "x")):
            with self.assertRaises(OpportunityError):
                call()

    def test_uncertain_goes_back_to_research(self):
        """Verifies FR-25 (§17): osäkert räknas inte som OK; ärendet går tillbaka till Research."""
        o = self.reg.open("lead-1", "terms", "Fiverr-automatik", "Får en AI sköta kundkontakten?", "R-03")
        self.reg.submit_findings("res-1", o.opportunity_id, "riktlinjerna säger inget", ("url:https://fiverr.com/ai",))
        o = self.reg.compliance_review("comp-1", o.opportunity_id, "uncertain", "inget uttryckligt stöd")
        self.assertEqual((o.stage, o.status), ("research", "unconfirmed_hypothesis"))
        o = self.reg.submit_findings("res-1", o.opportunity_id, "supporten bekräftar skriftligt", ("file:fiverr-svar.pdf",))
        self.assertEqual(o.stage, "compliance")

    def test_not_ok_closes_as_rejected(self):
        """Verifies FR-25: Compliance kan stoppa ett ärende; det avslutas som avvisat och kan inte öppnas igen."""
        o = self.reg.open("lead-1", "channel", "x", "y")
        self.reg.submit_findings("res-1", o.opportunity_id, "x", ETSY)
        o = self.reg.compliance_review("comp-1", o.opportunity_id, "not_ok", "förbjuden varutyp")
        self.assertEqual((o.stage, o.status), ("closed", "rejected"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute("UPDATE opportunities SET stage = 'founders'")

    def test_rule_kinds_become_approved_rules(self):
        """Verifies D-011 och §29: en godkänd villkors- eller licensfråga blir en godkänd operativ regel."""
        o = self.through_cfo(kind="license", ref="R-07")
        o = self.reg.founder_decision("yorgo", o.opportunity_id, True, "Apache 2.0 tillåter kommersiellt bruk")
        self.assertEqual(o.status, "approved_rule")


class TestTax(OpportunityCase):
    def test_tax_needs_skatteverket_or_advisor_to_approve(self):
        """Verifies D-011: en skattefråga godkänns bara med underlag från Skatteverket eller en rådgivare."""
        o = self.through_cfo(kind="tax", ref="R-01")
        with self.assertRaises(OpportunityError) as ctx:
            self.reg.founder_decision("yorgo", o.opportunity_id, True, "låter rimligt")
        self.assertIn("Skatteverket", str(ctx.exception))
        o = self.reg.founder_decision("yorgo", o.opportunity_id, True, "bekräftat i telefon",
                                      ("url:https://www.skatteverket.se/svar/123",))
        self.assertEqual(o.status, "approved_rule")

    def test_tax_can_always_be_rejected(self):
        """Verifies D-011: att avvisa en skattefråga kräver inget särskilt underlag."""
        o = self.through_cfo(kind="tax", ref="R-08")
        self.assertEqual(self.reg.founder_decision("robin", o.opportunity_id, False, "för osäkert").status, "rejected")


class TestWhoMayDoWhat(OpportunityCase):
    def test_roles_per_step(self):
        """Verifies FR-25 (D-011): bara rätt roll gör varje steg, och bara grundarna beslutar."""
        o = self.reg.open("yorgo", "channel", "x", "y")
        for actor in ("cfo-1", "comp-1", "ceo-1"):
            with self.subTest(step="findings", actor=actor), self.assertRaises(OpportunityError):
                self.reg.submit_findings(actor, o.opportunity_id, "x", ETSY)
        self.reg.submit_findings("lead-1", o.opportunity_id, "x", ETSY)  # research_lead är Research
        with self.assertRaises(OpportunityError):
            self.reg.compliance_review("cfo-1", o.opportunity_id, "ok", "x")
        self.reg.compliance_review("comp-1", o.opportunity_id, "ok", "x")
        with self.assertRaises(OpportunityError):
            self.reg.cfo_estimate("comp-1", o.opportunity_id, "x", Money(1, "SIM"))
        self.reg.cfo_estimate("cfo-1", o.opportunity_id, "x", Money(-500, "SIM"))  # förlust är tillåtet
        for actor in ("ceo-1", "cfo-1"):
            with self.subTest(step="decision", actor=actor), self.assertRaises(OpportunityError):
                self.reg.founder_decision(actor, o.opportunity_id, True, "x")

    def test_worker_cannot_open_and_sources_are_required(self):
        """Verifies FR-25: en arbetsagent öppnar inte ärenden, och fynd utan källa avvisas."""
        with self.assertRaises(OpportunityError):
            self.reg.open("res-1", "channel", "x", "y")
        o = self.reg.open("ceo-1", "channel", "x", "y")
        for sources in ((), ("tro mig",)):
            with self.subTest(sources=sources), self.assertRaises(OpportunityError):
                self.reg.submit_findings("res-1", o.opportunity_id, "x", sources)

    def test_ref_unique_and_format(self):
        """Verifies FR-25: en fråga i QUESTIONS.md utreds bara i ett ärende åt gången."""
        self.reg.open("ceo-1", "channel", "x", "y", "R-02")
        for ref in ("R-02", "fråga 2"):
            with self.subTest(ref=ref), self.assertRaises(OpportunityError):
                self.reg.open("ceo-1", "channel", "x", "y", ref)

    def test_survives_restart_and_steps_are_append_only(self):
        """Verifies FR-03: ärendet och stegen finns kvar efter omstart och kan inte skrivas om."""
        o = self.through_cfo()
        self.db.close()
        self.start()
        o = self.reg.get(o.opportunity_id)
        self.assertEqual((o.stage, len(o.steps)), ("founders", 3))
        self.assertEqual([x.opportunity_id for x in self.reg.waiting_for("founders")], [o.opportunity_id])
        for sql in ("UPDATE opportunity_steps SET summary = 'annat'", "DELETE FROM opportunity_steps",
                    "UPDATE opportunities SET kind = 'tax'", "DELETE FROM opportunities"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.connection.execute(sql)


if __name__ == "__main__":
    unittest.main()
