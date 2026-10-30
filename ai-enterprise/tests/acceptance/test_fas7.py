"""Acceptanstester för §55 (pilotens villkor) och §62 (definition av färdigt system), masterprompten 2026-10-30.

Varje test motsvarar ett villkor. Villkor som inte kan provas i en test (till exempel att alla tidigare
kritiska tester är gröna) bevisas av CI och står i `docs/ACCEPTANCE-55-62.md`.
"""
import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from aie.authorization import PermissionDenied
from aie.config import load_config
from aie.governance.cli import build
from aie.memory import Database
from aie.monitoring import shutdown_logging
from aie.pilot.cli import import_platform_sales, live
import json

from aie.pilot.product import parse_idea
from aie.pilot.writer import write_product
from aie.system import build_system

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "tests" / "fixtures" / "gumroad" / "sales.csv"


RULE_IDEAS = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "rule_ideas.json").read_text())


class Fas7Pilot(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        self.dir = Path(tmp.name)
        self.root = self.dir / "data-pilot"
        self.product = write_product(parse_idea(RULE_IDEAS[2]), "# Guide\n", "rule", self.dir / "products")

    def cli(self, fn, *args, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            return fn(*args, **kw), out.getvalue()

    def prepare(self):
        return self.cli(live, ROOT / "config", "prepare", "robin", self.product, None, root=self.root)

    def open(self):
        config = load_config(self.root / "config")
        db = Database.open(self.root / "data", "prod")
        self.addCleanup(db.close)
        return config, db, build_system(config, db, self.root / "config")

    def test_55_2_start_budget_is_explicitly_set(self):
        code, text = self.prepare()
        self.assertEqual(code, 0, text)
        cap = load_config(ROOT / "config").risk.start_capital.amount_minor
        self.assertIn(f"Budgettak: {cap / 100:.2f} kr (START_CAPITAL)", text)

    def test_55_3_permissions_are_limited_in_the_pilot(self):
        self.prepare()
        config, db, system = self.open()
        with self.assertRaises(PermissionDenied):
            system.engine.require("res-1", "decision.record")  # utanför forskarens mandat
        with self.assertRaises(PermissionDenied):
            system.engine.require("ceo-1", "sim.spend")  # sim-verktyg finns inte i prod

    def test_55_4_protected_reserve_is_configured(self):
        self.prepare()
        config, db, system = self.open()
        self.assertGreater(config.risk.minimum_reserve.amount_minor, 0)
        self.assertEqual(config.system.environment, "prod")

    def test_55_5_kill_switch_blocks_agents_in_the_pilot(self):
        self.prepare()
        config, db, system = self.open()
        system.kill.engage("robin", "acceptanstest §55")
        with self.assertRaises(PermissionDenied):
            system.engine.require("ceo-1", "decision.record")  # nödstoppet stoppar allt utom läsning

    def test_55_6_bookkeeping_and_logging_work(self):
        self.prepare()
        self.cli(live, ROOT / "config", "approve", "robin", None, 1, root=self.root)
        code, text = self.cli(import_platform_sales, ROOT / "config", "robin", CSV, self.product, 10.0, None,
                              root=self.root, today="2026-11-10")
        self.assertEqual(code, 0, text)
        config, db, system = self.open()
        self.assertTrue(system.ledger.entries("SEK"))
        self.assertTrue(system.audit.verify().ok)

    def test_55_7_human_approval_is_required(self):
        code, text = self.prepare()
        request_id = int(re.search(r"förfrågan #(\d+)", text).group(1))
        config, db, system = self.open()
        gov = build(config, db, self.root / "config")
        self.assertEqual([r.request_id for r in gov.queue.pending()], [request_id])
        with self.assertRaises(Exception):
            gov.queue.approve("ceo-1", request_id, "en agent får inte godkänna")
        code, text = self.cli(import_platform_sales, ROOT / "config", "robin", CSV, self.product, 10.0, None,
                              root=self.root)
        self.assertEqual(code, 1)
        self.assertIn("inte godkänd", text)


# §62: varje punkt bevisas av ett befintligt test. Testet nedan kontrollerar att alla bevis finns.
PROOF_62 = {
    "Agenterna har specialiserade roller": "test_fas2.py::test_agents_have_identifiable_roles",
    "Företaget har en fungerande hierarki": "test_fas3.py::test_work_flows_down_the_chain_to_the_worker_who_does_it",
    "Uppgifter fördelas och följs upp": "test_fas2.py::test_task_assigned_done_and_traceable",
    "Agenter kan resonera tillsammans inför beslut": "test_fas3.py::test_cfo_and_cro_disagree_is_escalated_with_documented_dispute",
    "Befogenheter kontrolleras tekniskt": "test_fas2.py::test_tool_outside_mandate_denied_and_logged",
    "Kapital och budgetar registreras korrekt": "test_fas4.py::test_overrun_is_blocked",
    "Nettovinst kan beräknas och verifieras": "test_fas4.py::test_net_profit_from_entries",
    "Riskgränser och reserver respekteras": "test_fas4.py::test_reserve_and_reserved_tax_are_never_spent",
    "Misstag dokumenteras och följs upp": "test_fas5.py::test_a_stop_becomes_an_incident_traced_to_the_event",
    "Lärdomar sparas beständigt": "test_fas5.py::test_lesson_has_sources_status_and_history",
    "Förbättringar testas innan de används i produktion": "test_fas5.py::test_unconfirmed_hypothesis_cannot_change_shared_rules",
    "Agenter kan pausas och avvecklas kontrollerat": "test_fas2.py::test_suspended_agent_cannot_work",
    "Kritiska händelser kan granskas i efterhand": "test_fas3.py::test_from_decision_back_to_task_history_and_approvals",
    "Utvecklingen följer kostnadspolicyn": "test_fas1.py::test_no_network_no_third_party_imports",
    "Yorgo och Robin kan fortsätta utveckla projektet med gemensam dokumentation": "test_fas6.py::test_5_stop_and_restart_without_losing_critical_history",
}


class Paragraph62(unittest.TestCase):
    def test_every_testable_item_has_an_existing_proof(self):
        for item, proof in PROOF_62.items():
            file, name = proof.split("::")
            text = (ROOT / "tests" / "acceptance" / file).read_text(encoding="utf-8")
            self.assertIn(f"def {name}(", text, f"§62 '{item}': beviset {proof} saknas")


if __name__ == "__main__":
    unittest.main()
