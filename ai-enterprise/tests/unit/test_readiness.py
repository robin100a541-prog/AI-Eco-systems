"""Tester för bedömningen av om simuleringen är lönsam nog för riktiga pengar (D-048). Verifierar D-048,
D-047, §29, §54, §55, SR-11 och ER-15."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aie.authorization import load_permissions
from aie.config import ConfigError, load_config
from aie.monitoring import shutdown_logging
from aie.simulation import SimulationError, load_scenario
from aie.simulation.cli import simulate
from aie.simulation.readiness import evaluate, load_readiness_rules

ROOT = Path(__file__).resolve().parents[2]
FOUNDERS = frozenset({"robin", "yorgo"})
CAPITAL_BUDGETS = """config_version = 1
mode = "capital"
[departments.research]
share = 40
max_commitment = 20_000
risk_room = "medium"
purpose = "försök"
"""
QUICK = """config_version = 1
[readiness]
min_runs = 3
min_days = 40
recent_days = 14
min_margin_percent = 10
max_drawdown_percent = 20
first_real_investment = 50_000
next_real_investment = 100_000
"""


class ReadinessCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        self.dir = Path(tmp.name)
        self.config_dir = self.dir / "config"
        shutil.copytree(ROOT / "config", self.config_dir)
        (self.config_dir / "budgets.toml").write_text(CAPITAL_BUDGETS, encoding="utf-8")
        (self.config_dir / "simulation.toml").write_text(QUICK, encoding="utf-8")
        text = (self.config_dir / "system.toml").read_text(encoding="utf-8")
        text = text.replace('data_dir = "data"', f'data_dir = "{(self.dir / "data").as_posix()}"')
        text = text.replace('log_dir = "logs"', f'log_dir = "{(self.dir / "logs").as_posix()}"')
        (self.config_dir / "system.toml").write_text(text, encoding="utf-8")
        self.config = load_config(self.config_dir)
        self.departments = {m.department for m in load_permissions(self.config_dir).roles.values()}

    def scenario(self, name):
        return load_scenario(self.config_dir, name, self.departments, FOUNDERS)


class TestRules(ReadinessCase):
    def test_shipped_rules_and_validation(self):
        """Verifies D-048 och §29: reglerna kräver flera körningar; en enda körning godtas aldrig som bevis."""
        rules = load_readiness_rules(ROOT / "config")
        self.assertEqual((rules.min_runs, rules.min_days, rules.first_real_investment), (5, 90, 50_000))
        (self.config_dir / "simulation.toml").write_text(QUICK.replace("min_runs = 3", "min_runs = 1"),
                                                         encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_readiness_rules(self.config_dir)


class TestJudgement(ReadinessCase):
    def test_profitable_model_after_all_costs_is_recommended_but_never_acts(self):
        """Verifies D-048 och §54: lönsam efter avgifter, kostnader och skatt i alla körningar ger en rekommendation."""
        result = evaluate(self.config, self.config_dir, self.scenario("normal"))
        self.assertTrue(result.ready, result.reasons)
        self.assertEqual(len({r.seed for r in result.runs}), 3)  # olika seed: oberoende körningar
        self.assertTrue(all(r.fees_minor > 0 and r.after_tax_minor > 0 for r in result.runs))
        self.assertIn("500 kr", result.recommendation)
        self.assertIn("uttryckliga godkännande", result.recommendation)
        self.assertFalse((self.dir / "data").exists())  # huvuddatabasen rörs aldrig

    def test_losing_model_is_not_ready(self):
        """Verifies D-048 och §54 punkt 2: ett upplägg där allt går med förlust rekommenderas aldrig."""
        loss = (self.config_dir / "scenarios" / "loss.toml").read_text(encoding="utf-8")
        only_loss = loss.split("[[initiatives]]")
        (self.config_dir / "scenarios" / "allloss.toml").write_text(
            "[[initiatives]]".join(only_loss[:2]).replace('name = "loss"', 'name = "allloss"'), encoding="utf-8")
        result = evaluate(self.config, self.config_dir, self.scenario("allloss"))
        self.assertFalse(result.ready)
        self.assertTrue(any("saknar vinst" in r for r in result.reasons))
        self.assertIn("Inte redo", result.recommendation)

    def test_cutting_a_losing_initiative_keeps_the_company_profitable(self):
        """Verifies §54 punkt 2: systemet hittar förlustinitiativet och pausar det, och resten bär företaget."""
        result = evaluate(self.config, self.config_dir, self.scenario("loss"))
        self.assertTrue(all(r.after_tax_minor > 0 for r in result.runs), result.reasons)

    def test_too_few_runs_or_days_is_not_proof(self):
        """Verifies §29 och D-048: för få körningar eller för korta körningar räcker inte, hur bra de än är."""
        result = evaluate(self.config, self.config_dir, self.scenario("normal"), runs=2, days=20)
        self.assertFalse(result.ready)
        self.assertTrue(any("körningar" in r for r in result.reasons))
        self.assertTrue(any("dagar" in r for r in result.reasons))

    def test_only_in_sim(self):
        """Verifies SR-11 och ER-15: bedömningen körs bara med simulerade pengar."""
        prod = replace(self.config, system=replace(self.config.system, environment="prod"))
        with self.assertRaises(SimulationError):
            evaluate(prod, self.config_dir, self.scenario("normal"))

    def test_command_writes_a_report(self):
        """Verifies D-048 och §30: kommandot skriver en rapport med kontrollsumma som kan granskas i efterhand."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = simulate(self.config_dir, "evaluate", "normal")
        shutdown_logging()
        self.assertEqual(code, 0)
        self.assertIn("REKOMMENDATION", out.getvalue())
        (report,) = (self.dir / "data" / "reports").glob("readiness-normal-*.json")
        self.assertTrue(json.loads(report.read_text(encoding="utf-8"))["ready"])


if __name__ == "__main__":
    unittest.main()


class TestUnverifiedMarket(unittest.TestCase):
    def test_ready_is_only_a_hypothesis_without_real_sales(self):
        """Verifies §29 och D-062: "redo" är en hypotes tills riktiga försäljningsdata finns; antagandena är overifierade."""
        from aie.simulation.readiness import MARKET_NOTE, RunResult, _judge

        rules = load_readiness_rules(ROOT / "config")
        good = RunResult("s", rules.min_days, 100_000, 1_000, 1_000, 98_000, 10_000, 88_000, 5_000, 80.0,
                         900_000, 0.0, False, False, False)
        runs = (good,) * rules.min_runs
        hypo = _judge("normal", "scripted", runs, rules, rules.min_runs, rules.min_days)
        self.assertTrue(hypo.ready)
        self.assertTrue(hypo.recommendation.startswith("HYPOTES: "))
        self.assertIn(MARKET_NOTE, hypo.recommendation)
        self.assertEqual(hypo.as_dict()["market_assumptions"], "unverified")
        self.assertEqual(hypo.status, "redo som hypotes (overifierat)")
        real = _judge("normal", "scripted", runs, rules, rules.min_runs, rules.min_days, real_sales=True)
        self.assertFalse(real.recommendation.startswith("HYPOTES"))
        self.assertEqual(real.as_dict()["market_assumptions"], "verified")

    def test_sim_reports_say_the_market_is_unverified(self):
        """Verifies §57, §58: varje SIM-rapport anger att marknadsantagandena är overifierade."""
        from aie.reporting.daily import DailyReport
        from aie.reporting.periodic import PeriodicReport

        self.assertIn("OVERIFIERADE", DailyReport("2027-01-01", "SIM", ()).render())
        self.assertIn("OVERIFIERADE", PeriodicReport("2027-01-01", "2027-01-02", "SIM", (), ()).render())
        self.assertNotIn("OVERIFIERADE", DailyReport("2027-01-01", "SEK", ()).render())
