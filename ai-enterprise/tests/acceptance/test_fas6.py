"""Acceptanstester för Fas 6 (konstitutionen §54, ROADMAP 6b-5). Ett eller flera per kriterium.

Körs mot riktiga simuleringar av repots scenarier (SIM, inga externa anrop), med det byggda systemet.
"""
import unittest
from dataclasses import replace

from aie.budget import Risk, SpendRequest
from aie.ledger import (
    Approval,
    EntryDraft,
    EntryType,
    LedgerError,
    Status,
    compute_result,
)
from aie.reporting.daily import daily_report
from aie.reporting.periodic import periodic_report
from aie.simulation import Simulation, SimulationError
from tests.unit.test_simulation import SimCase


class TestFas6(SimCase):
    def test_1_simulated_money_is_never_mixed_with_real_money(self):
        """§54: simulerade pengar blandas inte ihop med riktiga. Bara SIM bokförs, och simuleringen vägrar prod."""
        sim = self.start("normal")
        sim.run(3)
        self.assertEqual({e.currency for e in self.system.ledger.entries()}, {"SIM"})
        with self.assertRaises(LedgerError):
            self.system.ledger.record("robin", EntryDraft("riktig-1", "finance", 100, "SEK", EntryType.CAPITAL_IN,
                                                          "x", Approval.NOT_REQUIRED, ("decision:1",)))
        prod = replace(self.config, system=replace(self.config.system, environment="prod"))
        with self.assertRaises(SimulationError):
            Simulation.start(self.system, prod, sim.scenario, "yorgo", self.clock)

    def test_2_loss_making_initiatives_are_identified(self):
        """§54: förlustbringande initiativ identifieras, av stop-loss och i den periodiska rapporten."""
        sim = self.start("loss")
        days = sim.run()
        self.assertTrue(any("tryckta-affischer" in d["stopped"] for d in days))
        report = periodic_report(self.system, days[0]["date"], days[-1]["date"])
        figures = {f.initiative: f for f in report.initiatives}
        self.assertLess(figures["tryckta-affischer"].net_minor, 0)
        self.assertIn("pröva att stoppa tryckta-affischer", dict(report.points)["Rekommenderade förändringar"])

    def test_3_risk_limits_work(self):
        """§54: riskgränser fungerar. En utgift över MAX_SINGLE_TRANSACTION och en efter nödstopp nekas."""
        sim = self.start("normal")
        sim.run(1)
        limit = self.config.risk.max_single_transaction.amount_minor
        check = self.system.budget.check("cfo-1", SpendRequest("research", limit + 1, "SIM", "test", Risk.LOW))
        self.assertFalse(check.allowed)
        self.system.kill.engage("robin", "acceptanstest")
        check = self.system.budget.check("cfo-1", SpendRequest("research", 1, "SIM", "test", Risk.LOW))
        self.assertFalse(check.allowed)

    def test_4_reports_match_the_simulated_transactions(self):
        """§54: rapporterna motsvarar simulerade transaktionsdata, dag för dag och för hela perioden."""
        sim = self.start("normal")
        days = sim.run(5)
        entries = self.system.ledger.entries("SIM")
        for d in days:
            values = dict(daily_report(self.system, d["date"]).points)
            today = tuple(e for e in entries if e.recorded_at[:10] == d["date"])
            settled = [e for e in today if e.status is Status.SETTLED]
            revenue = sum(e.amount_minor for e in settled if e.entry_type is EntryType.REVENUE) - sum(
                e.amount_minor for e in settled if e.entry_type is EntryType.REFUND)  # netto efter återbetalningar
            self.assertTrue(values["Intäkter under perioden"].startswith(f"{revenue} SIM"), (d["date"], values))
            net = compute_result(today, "SIM").net_minor
            self.assertTrue(values["Realiserad nettovinst eller nettoförlust"].startswith(f"{net} SIM"))
        whole = periodic_report(self.system, days[0]["date"], days[-1]["date"])
        net = compute_result(entries, "SIM").net_minor
        self.assertTrue(dict(whole.points)["Nettovinst"].startswith(f"{net} SIM"))
        self.assertEqual(sum(f.net_minor for f in whole.initiatives), net)

    def test_5_stop_and_restart_without_losing_critical_history(self):
        """§54: systemet kan stoppas och återstartas utan att förlora kritisk historik."""
        sim = self.start("normal")
        sim.run(3)
        entries = [e.entry_id for e in self.system.ledger.entries()]
        audit = sum(1 for _ in self.system.audit.entries())
        self.db.close()
        system = self.open()
        sim = Simulation.resume(system, self.config, self.clock)
        self.assertEqual([e.entry_id for e in system.ledger.entries()], entries)
        self.assertGreaterEqual(sum(1 for _ in system.audit.entries()), audit)
        self.assertTrue(system.audit.verify().ok)
        sim.run(2)
        self.assertEqual(sim.last_day, 5)


if __name__ == "__main__":
    unittest.main()
