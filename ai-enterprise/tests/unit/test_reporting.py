"""Tester för src/aie/reporting (Fas 2). Verifierar FR-08, ER-09, ER-11 och ER-15."""
import json
import unittest

from aie.config import Money
from aie.reporting import Claim, ClaimKind, Report, ReportError

K = ClaimKind
SIM = "SIM"


def report(*claims, **kwargs):
    return Report(author=kwargs.get("author", "res-1"), title=kwargs.get("title", "R-02 Gumroad"), claims=claims)


class TestValidReports(unittest.TestCase):
    def test_all_ten_kinds_exist(self):
        """Verifies FR-08: alla tio kategorier i §7 finns, och inga andra."""
        self.assertEqual(
            {k.value for k in K},
            {"hypothesis", "forecast", "plan", "attempt", "done", "observed", "verified",
             "booked", "realized_revenue", "realized_net_profit"},
        )

    def test_full_report_round_trips_as_json(self):
        """Verifies FR-08: en rapport med alla kategorier kan sparas som JSON och läsas tillbaka exakt."""
        original = report(
            Claim(K.HYPOTHESIS, "mallar för småföretag säljer"),
            Claim(K.FORECAST, "10 sålda första månaden", amount=Money(50_000, SIM)),
            Claim(K.PLAN, "lägg upp 3 mallar"),
            Claim(K.ATTEMPT, "testannons"),
            Claim(K.DONE, "3 mallar publicerade", ("task:7",)),
            Claim(K.OBSERVED, "120 besökare", ("url:https://example.com/stats",)),
            Claim(K.VERIFIED, "siffran stämmer med plattformens rapport", ("file:reports/r2.csv",)),
            Claim(K.BOOKED, "försäljning bokförd", ("ledger:41",), Money(15_000, SIM)),
            Claim(K.REALIZED_REVENUE, "mottagen betalning", ("ledger:41",), Money(15_000, SIM)),
            Claim(K.REALIZED_NET_PROFIT, "efter avgifter", ("ledger:41", "ledger:42"), Money(-2_500, SIM)),
        )
        text = json.dumps(original.to_dict(), ensure_ascii=False)
        self.assertEqual(Report.from_dict(json.loads(text)), original)

    def test_hypothesis_needs_no_evidence(self):
        """Verifies FR-08: hypoteser, planer och försök kräver inget underlag."""
        r = report(Claim(K.HYPOTHESIS, "x"), Claim(K.PLAN, "y"), Claim(K.ATTEMPT, "z"))
        self.assertEqual(len(r.by_kind(K.PLAN)), 1)


class TestInvalidReports(unittest.TestCase):
    def assert_invalid(self, *claims, fragments=()):
        with self.assertRaises(ReportError) as ctx:
            report(*claims)
        joined = "\n".join(ctx.exception.errors)
        for fragment in fragments:
            self.assertIn(fragment, joined)
        return ctx.exception

    def test_done_without_evidence(self):
        """Verifies FR-08 (§7): inget påstående om genomfört arbete utan underlag."""
        for kind in (K.DONE, K.OBSERVED, K.VERIFIED):
            with self.subTest(kind=kind):
                self.assert_invalid(Claim(kind, "klart"), fragments=("underlag krävs",))

    def test_realized_figures_must_point_to_ledger(self):
        """Verifies ER-09: realiserade siffror kräver en ledgerpost, inte bara en uppgift eller fil."""
        self.assert_invalid(
            Claim(K.REALIZED_REVENUE, "betalt", ("task:3",), Money(100, SIM)),
            fragments=("måste peka på en ledgerpost",),
        )

    def test_realized_figures_need_amount(self):
        """Verifies ER-11: en realiserad intäkt utan belopp är ingen intäkt."""
        self.assert_invalid(Claim(K.REALIZED_REVENUE, "betalt", ("ledger:1",)), fragments=("belopp krävs",))

    def test_amount_not_allowed_on_hypothesis_or_done(self):
        """Verifies ER-11: en hypotes eller ett genomfört arbete kan inte bära en summa som ser ut som pengar."""
        self.assert_invalid(
            Claim(K.HYPOTHESIS, "kan ge mycket", amount=Money(1_000_000, SIM)),
            Claim(K.DONE, "sålt", ("task:1",), Money(500, SIM)),
            fragments=("belopp får bara anges",),
        )

    def test_negative_only_for_net_profit(self):
        """Verifies FR-08: bara nettoresultatet kan vara negativt (förlust)."""
        self.assert_invalid(
            Claim(K.REALIZED_REVENUE, "x", ("ledger:1",), Money(-1, SIM)), fragments=("kan inte vara negativt",)
        )

    def test_mixed_currencies_rejected(self):
        """Verifies ER-15: SIM och SEK i samma rapport avvisas."""
        self.assert_invalid(
            Claim(K.FORECAST, "x", amount=Money(1, "SIM")),
            Claim(K.BOOKED, "y", ("ledger:1",), Money(1, "SEK")),
            fragments=("blandade valutor",),
        )

    def test_amount_must_be_integer(self):
        """Verifies ER-01: belopp i en rapport är heltal i minsta enhet."""
        self.assert_invalid(Claim(K.FORECAST, "x", amount=Money(10.5, SIM)), fragments=("heltal",))

    def test_evidence_format(self):
        """Verifies FR-08: underlag måste vara en kontrollerbar referens."""
        self.assert_invalid(Claim(K.DONE, "x", ("lita på mig",)), fragments=("ogiltigt underlag",))

    def test_all_errors_collected(self):
        """Verifies FR-08: alla fel i rapporten listas på en gång."""
        error = self.assert_invalid(
            Claim(K.DONE, ""),
            Claim(K.REALIZED_NET_PROFIT, "y"),
        )
        self.assertGreaterEqual(len(error.errors), 4)

    def test_empty_report_rejected(self):
        """Verifies FR-08: en rapport utan författare, titel eller påståenden avvisas."""
        with self.assertRaises(ReportError) as ctx:
            Report(author=" ", title="", claims=())
        self.assertEqual(len(ctx.exception.errors), 3)


if __name__ == "__main__":
    unittest.main()
