"""Fas 7b: förbered, godkänn och importera Gumroads försäljning. Verifierar ER-15, ER-23, ER-13 och D-049."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from aie.config import load_config
from aie.governance.cli import build
from aie.ledger import EntryType
from aie.memory import Database
from aie.monitoring import shutdown_logging
from aie.pilot.cli import import_platform_sales, live
from aie.pilot.live import PilotError, import_sales, parse_sales_csv, pilot_config
from aie.pilot.product import RULE_IDEAS, parse_idea
from aie.pilot.writer import write_product
from aie.system import build_system

from .fixture_config import ROOT

CSV = ROOT / "tests" / "fixtures" / "gumroad" / "sales.csv"


class PilotLive(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        self.dir = Path(tmp.name)
        self.root = self.dir / "data-pilot"
        self.product = write_product(parse_idea(RULE_IDEAS[2]), "# Guide\n", "rule", self.dir / "products")
        self.config_dir = ROOT / "config"

    def run_cli(self, fn, *args, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = fn(*args, **kw)
        return code, out.getvalue()

    def prepare_and_approve(self):
        code, text = self.run_cli(live, self.config_dir, "prepare", "robin", self.product, None, root=self.root)
        self.assertEqual(code, 0, text)
        self.assertIn("Budgettak: 500.00 kr", text)
        self.assertIn("Upplysning om AI-användning", text)
        code, text = self.run_cli(live, self.config_dir, "approve", "Robin", None, 1, root=self.root)
        self.assertEqual(code, 0, text)
        self.assertIn("approved", text)

    def importing(self, net, today="2026-11-10", csv=CSV):
        return self.run_cli(import_platform_sales, self.config_dir, "robin", csv, self.product, 10.0, net, root=self.root,
                            today=today)

    def system(self):
        config = load_config(self.root / "config")
        db = Database.open(self.root / "data", "prod")
        self.addCleanup(db.close)
        return build_system(config, db, self.root / "config")


class TestImport(PilotLive):
    def test_import_refunds_duplicates_and_reconciliation(self):
        self.prepare_and_approve()
        code, text = self.importing(net=(3 * 10.30 - 12.00))
        self.assertEqual(code, 0, text)
        self.assertIn("Importerat 3 försäljningar (1 återbetalda, 1 dubbletter", text)
        self.assertIn("netto 189.00 kr", text)  # 360 - 51 - 120
        system = self.system()
        entries = [e for e in system.ledger.entries("SEK") if e.initiative == "pilot-f-skatt-guide"]
        self.assertEqual(sum(1 for e in entries if e.entry_type is EntryType.REFUND), 1)
        self.assertEqual(system.ledger.entries("SIM"), ())  # aldrig SIM i pilotens databas
        self.assertGreater(system.tax.reserved_minor("SEK"), 0)
        code, text = self.importing(net=(3 * 10.30 - 12.00))  # samma fil igen: inget bokförs två gånger
        self.assertIn("Importerat 0 försäljningar", text)

    def test_mismatch_opens_incident(self):
        self.prepare_and_approve()
        code, text = self.importing(net=50.00)
        self.assertEqual(code, 2)
        self.assertIn("AVSTÄMNING STÄMMER INTE", text)
        titles = [i.title for i in self.system().incidents.open_incidents()]
        self.assertIn("Avstämning mot Gumroad stämmer inte (ER-23)", titles)

    def test_no_import_before_approval(self):
        code, text = self.importing(net=None)
        self.assertEqual(code, 1)
        self.assertIn("inte godkänd", text)

    def test_sim_database_refuses_real_sales(self):
        db = Database.open(self.dir / "sim", "sim")
        self.addCleanup(db.close)
        system = build_system(load_config(self.config_dir), db, self.config_dir)
        with self.assertRaises(PilotError):
            import_sales(system, "robin", "pilot-x", CSV.read_text(), 10.0, None)

    def test_parse_requires_columns(self):
        with self.assertRaises(PilotError):
            parse_sales_csv("Name,Price\nx,1\n")


class TestStops(PilotLive):
    def test_no_sales_for_60_days_blocks_spend_and_advises_unpublish(self):
        self.prepare_and_approve()
        empty = self.dir / "empty.csv"
        empty.write_text("Purchase ID,Purchase Date,Sale Price ($),Fees ($)\n")
        code, text = self.importing(net=None, today="2027-03-01", csv=empty)
        self.assertIn("STOPP: ingen försäljning på 60 dagar", text)
        self.assertIn("avpublicera", text)
        self.assertTrue(self.system().protected.state().protected)

    def test_refund_ratio_stops(self):
        self.prepare_and_approve()
        refunds = self.dir / "refunds.csv"
        refunds.write_text("Purchase ID,Purchase Date,Sale Price ($),Fees ($),Refunded?\n"
                           + "".join(f"R{i},2026-11-0{i},12.00,1.70,{'true' if i == 1 else 'false'}\n"
                                     for i in range(1, 4)))
        code, text = self.importing(net=None, csv=refunds)
        self.assertIn("1 återbetalningar på 3 försäljningar", text)

    def test_pilot_config_is_prod_sek(self):
        out = pilot_config(self.config_dir, self.dir / "p")
        config = load_config(out)
        self.assertEqual((config.system.environment, config.system.base_currency), ("prod", "SEK"))
        self.assertEqual(config.risk.start_capital.amount_minor, load_config(self.config_dir).risk.start_capital.amount_minor)


if __name__ == "__main__":
    unittest.main()
