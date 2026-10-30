"""Tester för utfall från verkligheten (PR 10, D-062). Verifierar D-062, D-058, D-006 och §29."""
import contextlib
import io
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.monitoring import shutdown_logging
from aie.results import MIN_DAYS, VERIFIED, ResultError, ResultStore
from aie.results.cli import results as results_cli
from aie.simulation.assessment import (
    apply_observed,
    drop_replaced,
    load_assessment_rules,
    scenario_inputs,
)

from .fixture_config import TEST_CONFIG
from .test_registry import INITIATIVE, PLATFORM, RegisterCase

HEADER = "day,initiative,visitors,orders,revenue_minor,refunds_minor,fees_minor,costs_minor,currency,source,note\n"
SOURCE = "https://exempel.se/rapport"


def csv_rows(days=MIN_DAYS, initiative="mallar", visitors=40, orders=2, currency="SEK", source=SOURCE):
    return HEADER + "".join(
        f"2027-02-{d:02d},{initiative},{visitors},{orders},{orders * 4900},{4900 if d == 1 else 0},{orders * 300},0,"
        f"{currency},{source}/{d},dag {d}\n" for d in range(1, days + 1))


class ResultCase(RegisterCase):
    def setUp(self):
        super().setUp()
        self.approved_pair()
        self.store = ResultStore(self.db, AuditStub(), frozenset({"robin", "yorgo"}), self.register,
                                 clock=lambda: "2027-03-01T12:00:00+00:00")


class AuditStub:
    def __init__(self):
        self.rows = []

    def append(self, actor, action, details):
        self.rows.append((actor, action, details))


class TestImport(ResultCase):
    def test_import_is_idempotent_and_append_only(self):
        """Verifies D-062: samma rad två gånger sparas en gång, och utfall kan aldrig ändras eller raderas."""
        self.assertEqual(self.store.import_csv("yorgo", csv_rows()), (MIN_DAYS, 0))
        self.assertEqual(self.store.import_csv("robin", csv_rows()), (0, MIN_DAYS))
        for sql in ("UPDATE real_results SET orders = 99", "DELETE FROM real_results"):
            with self.assertRaises(sqlite3.DatabaseError):
                with self.db.transaction() as tx:
                    tx.execute(sql)
        (o,) = self.store.observed("mallar")
        self.assertEqual((o.days, o.orders, o.visitors_per_day, o.conversion_bp, o.fee_per_order_minor),
                         (MIN_DAYS, 2 * MIN_DAYS, 40, 500, 300))
        self.assertEqual(o.net_minor, 2 * MIN_DAYS * (4900 - 300) - 4900)
        self.assertEqual(len(o.sources), MIN_DAYS)

    def test_a_bad_row_rejects_the_whole_file(self):
        """Verifies D-062 och §29: varje rad behöver en källa; fel samlas och inget sparas."""
        good = csv_rows(days=1).splitlines()[1]
        broken = {
            "framtid": good.replace("2027-02-01", "2027-04-01"),
            "källa": good.replace(f"{SOURCE}/1", ""),
            "antagande": good.replace(f"{SOURCE}/1", "antagande enligt mig"),
            "initiativ": good.replace(",mallar,", ",okänt,"),
            "decimal": good.replace(",40,", ",4.5,"),
            "negativ": good.replace(",40,", ",-1,"),
            "valuta": good.replace(",SEK,", ",EUR,"),
            "order": good.replace(",40,2,", ",1,2,"),
        }
        for name, row in broken.items():
            with self.subTest(name), self.assertRaises(ResultError):
                self.store.import_csv("yorgo", HEADER + good + "\n" + row + "\n")
        with self.assertRaisesRegex(ResultError, "kolumnerna"):
            self.store.import_csv("yorgo", "day,initiative\n2027-02-01,mallar\n")
        self.assertEqual(self.store.observed("mallar"), ())

    def test_only_founders_import(self):
        """Verifies D-062: en agent kan aldrig skriva in utfall."""
        with self.assertRaisesRegex(ResultError, "grundare"):
            self.store.import_csv("res-1", csv_rows())


class TestUseBeforeAssumptions(ResultCase):
    def market(self, fees=None):
        rules = load_assessment_rules(TEST_CONFIG)
        platform = PLATFORM | {"fees": fees or PLATFORM["fees"]}
        market, _, assumptions = scenario_inputs("mallar", INITIATIVE, platform, rules)
        return market, assumptions, rules, platform

    def test_enough_verified_days_replace_the_assumptions(self):
        """Verifies D-062: minst MIN_DAYS dagar ersätter besökare, konvertering, returer och okänd avgift."""
        self.store.import_csv("yorgo", csv_rows(currency="USD"))
        (o,) = self.store.observed("mallar")
        market, assumptions, rules, platform = self.market()
        self.assertTrue(any(a.startswith("efterfrågan") for a in assumptions))
        new, verified = apply_observed(market, o, platform["fees"], rules)
        self.assertEqual((new.visitors, new.conversion_bp, new.fee_bp), (40, 500, 0))
        self.assertEqual(new.fee_fixed, 300 * rules.usd_cent_in_sim_minor)
        self.assertTrue(all(v.startswith(VERIFIED) and SOURCE in v for v in verified))
        left = drop_replaced(assumptions, verified)
        self.assertFalse(any(a.startswith(("efterfrågan", "procentavgiften", "avgiften per order")) for a in left))
        self.assertTrue(any("skattespår" in a for a in left))  # det som inte är uppmätt förblir ett antagande

    def test_too_few_days_or_known_fees_change_nothing_they_should_not(self):
        """Verifies D-062: färre än MIN_DAYS dagar ersätter inget, och kända avgifter skrivs inte över."""
        self.store.import_csv("yorgo", csv_rows(days=MIN_DAYS - 1))
        (o,) = self.store.observed("mallar")
        market, assumptions, rules, platform = self.market()
        self.assertEqual(apply_observed(market, o, platform["fees"], rules), (market, []))
        self.store.import_csv("yorgo", csv_rows(days=MIN_DAYS))
        (o,) = self.store.observed("mallar")
        known = PLATFORM["fees"] | {"percent_bp": 650, "per_order_minor": 20}
        market, _, rules, platform = self.market(known)
        new, verified = apply_observed(market, o, known, rules)
        self.assertEqual((new.fee_bp, new.fee_fixed), (market.fee_bp, market.fee_fixed))
        self.assertFalse(any("avgift" in v for v in verified))


class TestReport(ResultCase):
    def test_report_shows_forecast_against_outcome(self):
        """Verifies D-062: rapporten visar utfall märkt verifierat och prognos märkt simulerat."""
        self.store.import_csv("yorgo", csv_rows())
        report = self.store.report("mallar")
        (row,) = report["results"]
        self.assertEqual(row["label"], VERIFIED)
        self.assertEqual(row["forecast"]["label"], "simulerat")
        self.assertEqual(row["forecast"]["conversion_bp"], INITIATIVE["demand"]["conversion_bp"])
        self.assertEqual(row["outcome"]["conversion_bp"], 500)
        self.assertIsNotNone(row["forecast"]["assessment_id"])
        self.assertTrue(row["enough_days"])


class TestCommand(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        self.dir = Path(tmp.name)
        self.config_dir = self.dir / "config"
        shutil.copytree(TEST_CONFIG, self.config_dir)
        text = (self.config_dir / "system.toml").read_text(encoding="utf-8")
        text = text.replace('data_dir = "data"', f'data_dir = "{(self.dir / "data").as_posix()}"')
        text = text.replace('log_dir = "logs"', f'log_dir = "{(self.dir / "logs").as_posix()}"')
        (self.config_dir / "system.toml").write_text(text, encoding="utf-8")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = results_cli(self.config_dir, *args)
        shutdown_logging()
        return code, out.getvalue(), err.getvalue()

    def test_import_list_and_report(self):
        """Verifies D-062: kommandot vägrar okända initiativ och visar tomma listor ärligt."""
        path = self.dir / "utfall.csv"
        path.write_text(csv_rows().replace("2027-02-", "2026-09-"), encoding="utf-8")  # kommandot har riktig tid
        code, _, err = self.run_cli("import", str(path), "yorgo")
        self.assertEqual(code, 1)
        self.assertIn("finns inte i registret", err)
        self.assertEqual(self.run_cli("list")[1].strip(), "Inga utfall importerade.")
        code, out, _ = self.run_cli("report", "mallar")
        self.assertIn("inga utfall importerade", out)
        self.add_initiative()
        code, out, err = self.run_cli("import", str(path), "yorgo")
        self.assertEqual((code, out.split(" nya")[0]), (0, str(MIN_DAYS)), err)
        self.assertIn(VERIFIED, self.run_cli("list")[1])
        code, out, _ = self.run_cli("report", "mallar")
        self.assertIn("ingen godkänd bedömning", out)
        self.assertIn("utfall", out)

    def add_initiative(self):
        from aie import runtime
        from aie.system import build_system

        config = runtime._load(self.config_dir, console=False)
        with runtime._open(config) as db:
            register = build_system(config, db, self.config_dir).register
            register.record("yorgo", "platform", "plattform-a", "idea", PLATFORM, "test")
            register.record("yorgo", "initiative", "mallar", "idea", INITIATIVE, "test")
        shutdown_logging()
