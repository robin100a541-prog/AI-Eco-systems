"""Tester för övervakning (FR-24, §16) och den periodiska rapporten (FR-22, §58), D-046."""
import unittest

from aie.ledger import EntryType
from aie.reporting.monitor import LOOP_REPEATS, monitor
from aie.reporting.periodic import POINTS, periodic_report

from .test_system import SystemCase


class TestMonitor(SystemCase):
    def kinds(self):
        return {(f.kind, f.subject) for f in monitor(self.system)}

    def test_loop_and_repeated_work_are_found(self):
        """Verifies FR-24: en loop (samma sak i rad) och upprepat arbete upptäcks per agent."""
        for _ in range(LOOP_REPEATS):
            self.system.audit.append("res-1", "research.search", {"q": "samma"})
        for i in range(3):
            self.system.audit.append("lead-1", "task.assign", {"task": 7})
            self.system.audit.append("lead-1", "task.note", {"n": i})
        kinds = self.kinds()
        self.assertIn(("loop", "res-1"), kinds)
        self.assertNotIn(("repeated_work", "res-1"), kinds)  # en loop räknas inte två gånger
        self.assertIn(("repeated_work", "lead-1"), kinds)
        self.assertNotIn(("loop", "lead-1"), kinds)

    def test_cost_without_value_is_found(self):
        """Verifies FR-24: ett initiativ med kostnad men utan intäkt, och en agent som bara anropar modellen."""
        self.book("k1", "research", EntryType.COST, 500)
        for _ in range(10):
            self.system.audit.append("res-1", "llm.call", {"tokens": 10})
        kinds = self.kinds()
        self.assertIn(("cost_without_value", "etsy"), kinds)
        self.assertIn(("cost_without_value", "res-1"), kinds)
        self.book("r1", "research", EntryType.REVENUE, 900)
        self.assertNotIn(("cost_without_value", "etsy"), self.kinds())


class TestPeriodicReport(SystemCase):
    def period(self):
        day = self.system.ledger.entries("SIM")[0].recorded_at[:10]
        return day, day

    def test_ten_points_and_comparable_initiative_figures(self):
        """Verifies FR-22: tio punkter i §58 och jämförbara nyckeltal per initiativ, ur ledgern."""
        self.book("in", "finance", EntryType.CAPITAL_IN, 1_000_000)
        self.book("r1", "research", EntryType.REVENUE, 3_000)
        self.book("k1", "research", EntryType.COST, 1_000)
        report = periodic_report(self.system, *self.period())
        values = dict(report.points)
        self.assertEqual([n for n, _ in report.points], list(POINTS))
        self.assertTrue(values["Nettovinst"].startswith("2000 SIM"))
        self.assertIn("in 1003000 SIM, ut 1000 SIM", values["Kassaflöde"])
        self.assertIn("3.00 kr intäkt per kr kostnad", values["Kostnadseffektivitet"])
        (etsy,) = report.initiatives
        self.assertEqual((etsy.net_minor, etsy.margin_percent, etsy.return_percent, etsy.days_active),
                         (2000, 100 * 2000 / 3000, 200.0, 1))
        self.assertIn("| etsy | 3000 | 1000 | 2000 |", report.render())

    def test_losses_become_recommendations_and_missing_data_is_stated(self):
        """Verifies FR-22: förlustinitiativ ger en rekommendation; saknade prognoser anges som SAKNAS."""
        self.book("k1", "research", EntryType.COST, 1_000)
        values = dict(periodic_report(self.system, *self.period()).points)
        self.assertIn("pröva att stoppa etsy", values["Rekommenderade förändringar"])
        self.assertTrue(values["Prognosprecision"].startswith("SAKNAS"))
        with self.assertRaises(ValueError):
            periodic_report(self.system, "2026-02-01", "2026-01-01")


class TestReportCli(unittest.TestCase):
    def test_report_commands_run_against_a_fresh_database(self):
        """Verifies FR-21, FR-22, FR-24: `python -m aie report` fungerar på en ny databas och anger saknade data."""
        import contextlib
        import io
        import shutil
        import tempfile
        from pathlib import Path

        from aie.reporting.cli import report

        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config"
            shutil.copytree(root / "config", config)
            text = (config / "system.toml").read_text(encoding="utf-8")
            lines = [f'data_dir = "{tmp}/data"' if ln.startswith("data_dir") else
                     f'log_dir = "{tmp}/logs"' if ln.startswith("log_dir") else ln for ln in text.splitlines()]
            (config / "system.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                for kind in ("daily", "periodic", "monitor"):
                    self.assertEqual(report(config, kind, None, None, None), 0, kind)
            self.assertIn("SAKNAS", out.getvalue())
            self.assertIn("# Periodisk rapport", out.getvalue())
            self.assertIn("0 fynd", out.getvalue())


if __name__ == "__main__":
    unittest.main()
