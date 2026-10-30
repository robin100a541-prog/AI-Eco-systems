"""Tester för den dagliga rapporten (FR-21, §57, D-045). Ledgern är facit: rapporten ska motsvara den."""
import unittest

from aie.ledger import EntryType, Status
from aie.reporting.daily import POINTS, daily_report, save_daily_reports

from .test_system import SystemCase


class TestDailyReport(SystemCase):
    def day(self):
        return self.system.ledger.entries("SIM")[0].recorded_at[:10]

    def test_all_eleven_points_match_the_ledger(self):
        """Verifies FR-21: elva punkter i §57; intäkter, kostnader och nettovinst stämmer med ledgern."""
        self.book("in-1", "finance", EntryType.CAPITAL_IN, 1_000_000)
        self.book("rev-1", "research", EntryType.REVENUE, 5_000)
        self.book("cost-1", "research", EntryType.COST, 1_200)
        self.book("fee-1", "research", EntryType.FEE, 300)
        self.book("cost-2", "research", EntryType.COST, 700, status=Status.PENDING)
        report = daily_report(self.system, self.day())
        values = dict(report.points)
        self.assertEqual([name for name, _ in report.points], list(POINTS))
        self.assertEqual(values["Intäkter under perioden"], "5000 SIM")
        self.assertEqual(values["Kostnader under perioden"], "1500 SIM")
        self.assertTrue(values["Realiserad nettovinst eller nettoförlust"].startswith("3500 SIM"))
        self.assertIn("PRELIMINÄRT", values["Realiserad nettovinst eller nettoförlust"])  # en post väntar
        self.assertGreaterEqual(int(values["Öppna ekonomiska åtaganden"].split()[0]), 700)  # + reserverad skatt
        self.assertIn("etsy", values["Aktiva affärsinitiativ"])
        self.assertIn("research", values["Budgetutnyttjande"])
        self.assertIn("1. **Disponibelt kapital:**", report.render())

    def test_missing_data_is_stated_not_shown_as_zero(self):
        """Verifies FR-21: saknas data för perioden står det SAKNAS med skäl, aldrig en tyst nolla."""
        report = daily_report(self.system, "2000-01-01")
        values = dict(report.points)
        for point in ("Intäkter under perioden", "Kostnader under perioden",
                      "Realiserad nettovinst eller nettoförlust"):
            self.assertTrue(values[point].startswith("SAKNAS: ledgern har inga poster"), values[point])
        self.assertIn("Data saknas för", report.render())
        self.book("in-1", "finance", EntryType.CAPITAL_IN, 1_000)
        quiet = dict(daily_report(self.system, "2999-01-01").points)  # en dag utan affärer efter start
        self.assertEqual(quiet["Kostnader under perioden"], "0 SIM (inga poster under dagen)")

    def test_stops_and_incidents_are_reported(self):
        """Verifies FR-21: nödstopp syns som risk och som kritiskt fel (incident)."""
        self.system.kill.engage("robin", "test av rapporten")
        self.system.tick()
        values = dict(daily_report(self.system, "2000-01-01").points)
        self.assertIn("NÖDSTOPP", values["Viktiga risker"])
        self.assertIn("incident #", values["Kritiska fel"])

    def test_one_report_file_per_business_day(self):
        """Verifies FR-21: en rapportfil per dag i ledgern."""
        self.book("in-1", "finance", EntryType.CAPITAL_IN, 1_000_000)
        paths = save_daily_reports(self.system, self.dir / "data")
        self.assertEqual([p.name for p in paths], [f"daily-{self.day()}.md"])
        self.assertIn("# Daglig rapport", paths[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
