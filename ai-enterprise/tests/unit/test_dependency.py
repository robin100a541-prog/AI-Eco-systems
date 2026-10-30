"""Tester för skyddet mot plattformsberoende (PR 7, D-059). Verifierar D-059, ER-02 och FR-20."""
import contextlib
import io
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

from aie.ledger import EntryType, Status
from aie.registry import SYSTEM, DependencyGuard, RegistryError
from aie.registry.cli import _print_dependency

from .test_registry import INITIATIVE, PLATFORM, RegisterCase
from .test_simulation import SimCase
from .evidence import evidence

LIMITS = SimpleNamespace(currency="SIM", max_platform_revenue_share=Decimal(60), min_active_platforms=2)


class FakeLedger:
    def __init__(self):
        self.rows = []

    def add(self, initiative, amount, kind=EntryType.REVENUE, at="2027-03-01T12:00:00+00:00"):
        self.rows.append(SimpleNamespace(initiative=initiative, amount_minor=amount, entry_type=kind,
                                         status=Status.SETTLED, recorded_at=at, economic_date=at[:10], currency="SIM"))

    def entries(self, currency=None):
        return tuple(self.rows)


class GuardCase(RegisterCase):
    def setUp(self):
        super().setUp()
        self.ledger = FakeLedger()
        self.limits = LIMITS
        self.guard = DependencyGuard(self.register, self.ledger, self, clock=lambda: "2027-03-10T00:00:00+00:00")
        self.register.dependency = self.guard

    # DependencyGuard läser gränserna från det här objektet, så att testerna kan ändra dem
    @property
    def currency(self):
        return self.limits.currency

    @property
    def max_platform_revenue_share(self):
        return self.limits.max_platform_revenue_share

    @property
    def min_active_platforms(self):
        return self.limits.min_active_platforms

    def platform(self, key, deps=()):
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "platform", key, status, PLATFORM | {"dependencies": list(deps)}, "test")

    def initiative(self, key, platform, approve=True):
        data = INITIATIVE | {"platform": platform}
        for status in ("investigated", "reviewed"):
            self.register.record("yorgo", "initiative", key, status, data, "test")
        a = self.register.assessments.record("yorgo", key, platform, data, self.register.get("platform", platform).data,
                                             evidence(), True)
        self.register.assessments.approve("yorgo", a.assessment_id, "ok")
        if approve:
            if self.register.get("platform", platform).status == "reviewed":
                self.register.set_status("yorgo", "platform", platform, "approved", "test")
            self.register.set_status("yorgo", "initiative", key, "approved", "test")

    def two_platforms(self, deps_a=("betalning-x",), deps_b=("betalning-y",)):
        self.platform("plattform-a", deps_a)
        self.platform("plattform-b", deps_b)
        self.initiative("mallar-a", "plattform-a")
        self.initiative("mallar-b", "plattform-b")


class TestGroups(GuardCase):
    def test_platforms_sharing_a_dependency_form_one_group(self):
        """Verifies D-059: plattformar med ett gemensamt kritiskt beroende räknas som en, även via en tredje."""
        self.platform("plattform-a", ["Betalning-X"])
        self.platform("plattform-b", ["betalning-x", "moln-1"])
        self.platform("plattform-c", ["moln-1"])
        self.platform("plattform-d", ["betalning-y"])
        groups = self.guard.groups()
        self.assertEqual(groups["plattform-a"], frozenset({"plattform-a", "plattform-b", "plattform-c"}))
        self.assertEqual(groups["plattform-d"], frozenset({"plattform-d"}))


class TestShares(GuardCase):
    def test_without_revenue_nothing_is_measured_or_blocked(self):
        """Verifies D-059: utan intäkter finns ingen andel; nya initiativ godkänns och inget varnas."""
        self.two_platforms()
        self.limits = replace_limits(max_platform_revenue_share=None, min_active_platforms=None)
        self.initiative("mallar-a2", "plattform-a")
        self.assertEqual(self.guard.warnings(), [])
        self.assertIsNone(self.guard.block_reason("plattform-a"))

    def test_concentrated_revenue_blocks_new_initiatives_on_that_platform_only(self):
        """Verifies D-059: på eller över gränsen stoppas nya initiativ där, men inte på andra plattformar."""
        self.two_platforms()
        self.ledger.add("mallar-a", 6_000)
        self.ledger.add("mallar-b", 4_000)
        self.ledger.add("mallar-a", 1_000, EntryType.REFUND)  # 5 000 av 9 000 = 55,6 %: under gränsen
        self.assertIsNone(self.guard.block_reason("plattform-a"))
        self.ledger.add("mallar-a", 1_000)  # 6 000 av 10 000 = 60 %: på gränsen
        with self.assertRaisesRegex(RegistryError, "MAX_PLATFORM_REVENUE_SHARE"):
            self.initiative("mallar-a2", "plattform-a")
        self.initiative("mallar-b2", "plattform-b")
        self.assertEqual(self.register.get("initiative", "mallar-b2").status, "approved")

    def test_existing_initiatives_can_always_be_paused_retired_or_activated(self):
        """Verifies D-059: säkerhetsåtgärder och redan godkända initiativ påverkas inte av spärren."""
        self.two_platforms()
        self.ledger.add("mallar-a", 9_000)
        self.ledger.add("mallar-b", 1_000)
        self.register.set_status("yorgo", "initiative", "mallar-a", "active", "test")
        self.register.set_status(SYSTEM, "initiative", "mallar-a", "paused", "test")
        self.register.set_status("yorgo", "initiative", "mallar-a", "retired", "test")
        self.assertEqual(self.register.get("initiative", "mallar-a").status, "retired")

    def test_a_shared_dependency_blocks_the_other_platform_too(self):
        """Verifies D-059: två plattformar med samma betalningsleverantör räknas ihop."""
        self.two_platforms(deps_a=("betalning-x",), deps_b=("betalning-x",))
        self.platform("plattform-c", ("betalning-z",))
        self.initiative("mallar-c", "plattform-c")
        self.ledger.add("mallar-a", 4_000)
        self.ledger.add("mallar-b", 3_000)
        self.ledger.add("mallar-c", 3_000)  # var för sig 40 % och 30 %, tillsammans 70 %
        self.assertIn("plattform-a, plattform-b", self.guard.block_reason("plattform-b"))
        self.assertIsNone(self.guard.block_reason("plattform-c"))

    def test_missing_limit_with_revenue_blocks_new_initiatives(self):
        """Verifies ER-02: en saknad gräns är aldrig obegränsad när det finns intäkter."""
        self.two_platforms()
        self.ledger.add("mallar-b", 1_000)
        self.limits = replace_limits(max_platform_revenue_share=None, min_active_platforms=None)
        with self.assertRaisesRegex(RegistryError, "saknas"):
            self.initiative("mallar-b2", "plattform-b")
        warnings = self.guard.warnings()
        self.assertTrue(any("MIN_ACTIVE_PLATFORMS saknas" in w for w in warnings))
        self.assertTrue(any("MAX_PLATFORM_REVENUE_SHARE saknas" in w for w in warnings))

    def test_old_revenue_falls_out_of_the_window(self):
        """Verifies D-059: andelen räknas de senaste 90 dagarna."""
        self.two_platforms()
        self.ledger.add("mallar-a", 9_000, at="2026-11-01T12:00:00+00:00")
        self.ledger.add("mallar-b", 1_000)
        self.assertIsNone(self.guard.block_reason("plattform-a"))
        self.assertIsNotNone(self.guard.block_reason("plattform-b"))


class TestReport(GuardCase):
    def test_report_and_warnings_say_what_to_do(self):
        """Verifies D-059: rapporten visar andel per grupp, hur mycket som måste flyttas och för få plattformar."""
        self.two_platforms()
        self.register.set_status(SYSTEM, "platform", "plattform-b", "paused", "kontot stängt")
        self.ledger.add("mallar-a", 8_000)
        self.ledger.add("mallar-b", 2_000)
        report = self.guard.report()
        self.assertEqual(report["total_revenue_minor"], 10_000)
        top = report["groups"][0]
        self.assertEqual((top["platforms"], top["percent"]), (["plattform-a"], 80.0))
        self.assertIn("minst 3334", top["action"])  # 8 000 / 13 334 < 60 %
        self.assertEqual(report["active_independent"], 1)
        warnings = self.guard.warnings()
        self.assertTrue(any("80.0 %" in w for w in warnings))
        self.assertTrue(any("bara 1 oberoende" in w for w in warnings))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            _print_dependency(report)
        self.assertIn("plattform-a", out.getvalue())


def replace_limits(**changes):
    return SimpleNamespace(**(vars(LIMITS) | changes))


class TestPlatformBan(SimCase):
    def test_platform_ban_on_day_30_stops_sales_there_and_the_company_continues(self):
        """Verifies D-059 och FR-20: kontot stängs dag 30, plattformen pausas, B säljer vidare utan nödstopp."""
        sim = self.start("platform_ban")
        sim.run()
        days = sim.days()
        self.assertEqual(len(days), 60)
        before = sum(d["initiatives"]["mallar-a"]["orders"] for d in days[:29])
        after = sum(d["initiatives"]["mallar-a"]["orders"] for d in days[29:])
        self.assertGreater(before, 0)
        self.assertEqual(after, 0)
        self.assertGreater(sum(d["initiatives"]["mallar-b"]["orders"] for d in days[29:]), 0)
        self.assertIn("kontot stängt", " ".join(days[29]["event_notes"]))
        register = self.system.register
        self.assertEqual(register.get("platform", "sim-platform_ban-plattform-a").status, "paused")
        self.assertEqual(register.get("platform", "sim-platform_ban-plattform-b").status, "approved")
        self.assertTrue(all(not d["paused"] for d in days), "ingen nödbroms eller skyddat läge")
        warnings = [e for e in self.system.audit.entries() if e.action == "dependency.warning"]
        self.assertTrue(warnings, "beroendet varnades aldrig")
        self.assertTrue(any("sim-platform_ban-plattform-a står för" in w
                            for e in warnings for w in e.details["warnings"]))
        self.assertIn("plattformen", register.spend_block_reason("research", "mallar-a"))

    def test_platform_ban_needs_a_known_platform_and_no_until(self):
        """Verifies D-059: platform_ban kräver en plattform ur [[platforms]] och gäller resten av körningen."""
        from aie.config import ConfigError
        from aie.simulation import parse_scenario

        from .test_simulation import DEPARTMENTS, FOUNDERS

        base = {"config_version": 1, "name": "x", "description": "x", "seed": "s", "days": 5,
                "start_date": "2027-01-01", "platforms": [{"key": "p", "dependencies": ["b"]}],
                "initiatives": [{"key": "a", "department": "research", "track": "partnership", "price": 100,
                                 "unit_cost": 0, "fee_fixed": 0, "fee_bp": 0, "visitors": 1, "conversion_bp": 1,
                                 "refund_bp": 0, "platform": "p"}],
                "events": [{"day": 2, "kind": "platform_ban", "platform": "p"}]}
        sc = parse_scenario(base, "ok", DEPARTMENTS, FOUNDERS)
        self.assertTrue(sc.events[0].active_on(5))
        for broken in ({"events": [{"day": 2, "kind": "platform_ban", "platform": "q"}]},
                       {"events": [{"day": 2, "kind": "platform_ban", "platform": "p", "until": 3}]},
                       {"initiatives": [{**base["initiatives"][0], "platform": "q"}]}):
            with self.subTest(broken=broken), self.assertRaises(ConfigError):
                parse_scenario(base | broken, "fel", DEPARTMENTS, FOUNDERS)
