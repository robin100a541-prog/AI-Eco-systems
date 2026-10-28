"""Tester för src/aie/config och `python -m aie check-config`.

Verifierar FR-02, ER-01, ER-02, ER-05, ER-15 och SR-10. Varje test skriver en egen
konfiguration i en temporär mapp och utgår från en giltig bas där bara ett fält ändras.
"""
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from decimal import Decimal
from pathlib import Path

from aie import __version__
from aie.config import LIMITS, ConfigError, Money, load_config

ROOT = Path(__file__).resolve().parents[2]
DROP = object()  # markerar att en nyckel ska tas bort ur basen

VALID_SYSTEM = {
    "config_version": 1,
    "environment": "sim",
    "data_dir": "data",
    "log_dir": "logs",
    "base_currency": "SIM",
}
VALID_RISK = {
    "currency": "SIM",
    "START_CAPITAL": 1_000_000,
    "MINIMUM_RESERVE": 300_000,
    "MAX_TOTAL_DRAWDOWN": 20,
    "MAX_SINGLE_EXPERIMENT_LOSS": 50_000,
    "MAX_DEPARTMENT_BUDGET": 200_000,
    "MAX_SINGLE_TRANSACTION": 20_000,
    "MAX_COMMITTED_CAPITAL": 400_000,
    "MAX_ALLOWED_UNVERIFIED_SPEND": 10_000,
    "HUMAN_APPROVAL_THRESHOLD": 10_000,
    "REINVESTMENT_POLICY": 50,
    "API_REINVEST_SHARE": 20,
    "API_MONTHLY_CAP": 0,
    "MAX_PLATFORM_REVENUE_SHARE": 60,  # D-059
    "MIN_ACTIVE_PLATFORMS": 2,  # D-059
}
PROD = {"environment": "prod", "base_currency": "SEK"}


def _toml(data: dict) -> str:
    """Minimal TOML-skrivare för platta tabeller. JSON-strängar och -tal är giltig TOML."""
    lines = []
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        else:
            lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def _merge(base: dict, changes: dict) -> dict:
    merged = {**base, **changes}
    return {k: v for k, v in merged.items() if v is not DROP}


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, system=None, risk=None, **extra_files):
        """Skriver bas + ändringar. `system`/`risk` = DROP tar bort hela filen."""
        for name, base, changes in (
            ("system.toml", VALID_SYSTEM, system),
            ("risk_limits.toml", VALID_RISK, risk),
        ):
            if changes is not DROP:
                (self.dir / name).write_text(_toml(_merge(base, changes or {})), encoding="utf-8")
        for name, text in extra_files.items():
            (self.dir / name.replace("__", ".")).write_text(text, encoding="utf-8")
        return self.dir

    def assert_invalid(self, *fragments, **write_args):
        """Kontrollerar att laddningen misslyckas och att varje fragment finns i något fel."""
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write(**write_args))
        joined = "\n".join(ctx.exception.errors)
        for fragment in fragments:
            self.assertIn(fragment, joined)
        return ctx.exception


class TestValidConfig(ConfigTestCase):
    def test_default_config_in_repo_loads(self):
        """Verifies FR-02: standardkonfigurationen i config/ är giltig och har alla gränser."""
        config = load_config(ROOT / "config")
        self.assertEqual(config.system.environment, "sim")
        self.assertTrue(config.system.is_simulation)
        self.assertEqual(config.risk.currency, "SIM")
        self.assertEqual(config.risk.missing, ())
        self.assertEqual(config.warnings, ())

    def test_config_is_frozen(self):
        """Verifies FR-02: konfigurationen kan inte ändras efter att den validerats."""
        config = load_config(self.write())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.risk.start_capital = Money(10**12, "SIM")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.system.environment = "prod"

    def test_amounts_are_integers_with_currency_and_percent_is_decimal(self):
        """Verifies ER-01: belopp är heltal i minsta enhet med valuta, procent är exakt Decimal."""
        config = load_config(self.write(risk={"MAX_TOTAL_DRAWDOWN": 12.5}))
        self.assertEqual(config.risk.start_capital, Money(1_000_000, "SIM"))
        self.assertEqual(config.risk.max_total_drawdown, Decimal("12.5"))

    def test_valid_prod_config_loads(self):
        """Verifies ER-15: prod med verklig valuta och alla gränser satta är giltig."""
        config = load_config(self.write(system=PROD, risk={"currency": "SEK"}))
        self.assertEqual(config.system.environment, "prod")
        self.assertEqual(config.risk.human_approval_threshold, Money(10_000, "SEK"))

    def test_limit_table_has_section_25_and_d009(self):
        """Verifies ER-02: alla tio §25-parametrar, båda D-009-parametrarna och båda D-059-parametrarna valideras."""
        self.assertEqual(set(LIMITS), set(VALID_RISK) - {"currency"})
        self.assertEqual(len(LIMITS), 14)

    def test_pyproject_version_matches_package(self):
        """Verifies DR-05: versionsnumret är detsamma i pyproject.toml och i paketet."""
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["version"], __version__)
        self.assertEqual(pyproject["project"]["dependencies"], [])


class TestEnvironment(ConfigTestCase):
    def test_missing_environment(self):
        """Verifies FR-02: saknad environment stoppar uppstart."""
        self.assert_invalid("environment saknas", system={"environment": DROP})

    def test_unknown_environment(self):
        """Verifies FR-02: okänd environment stoppar uppstart."""
        self.assert_invalid("'staging' är okänd", system={"environment": "staging"})

    def test_prod_with_sim_currency(self):
        """Verifies ER-15: prod får aldrig använda valutan SIM."""
        self.assert_invalid(
            "base_currency = 'SIM' är inte tillåtet i prod",
            "currency = 'SIM' är inte tillåtet i prod",
            system={"environment": "prod"},
        )

    def test_sim_with_real_currency(self):
        """Verifies ER-15: sim får aldrig använda en verklig valuta."""
        self.assert_invalid(
            "base_currency = 'SEK' är en verklig valuta",
            "currency = 'SEK' är en verklig valuta",
            system={"base_currency": "SEK"},
            risk={"currency": "SEK"},
        )

    def test_currency_must_match_between_files(self):
        """Verifies ER-15: risk_limits.toml och system.toml måste ha samma valuta."""
        self.assert_invalid(
            "matchar inte base_currency", system=PROD, risk={"currency": "EUR"}
        )

    def test_unsupported_config_version(self):
        """Verifies FR-02: en okänd config_version stoppar uppstart."""
        self.assert_invalid("config_version = 2 stöds inte", system={"config_version": 2})


class TestLimits(ConfigTestCase):
    def test_negative_amount(self):
        """Verifies FR-02: negativa belopp avvisas."""
        self.assert_invalid("MAX_SINGLE_TRANSACTION = -1 är negativt", risk={"MAX_SINGLE_TRANSACTION": -1})

    def test_amount_must_be_integer_minor_units(self):
        """Verifies ER-01: belopp måste vara heltal i minsta enhet, inte flyttal eller bool."""
        error = self.assert_invalid(
            "START_CAPITAL = 10.5 måste vara ett heltal",
            "API_MONTHLY_CAP = True måste vara ett heltal",
            risk={"START_CAPITAL": 10.5, "API_MONTHLY_CAP": True},
        )
        self.assertEqual(len(error.errors), 2)

    def test_percent_out_of_range(self):
        """Verifies FR-02: procentsatser utanför 0–100 avvisas, både över och under."""
        self.assert_invalid(
            "MAX_TOTAL_DRAWDOWN = 101 ligger utanför 0–100",
            "REINVESTMENT_POLICY = -5 ligger utanför 0–100",
            risk={"MAX_TOTAL_DRAWDOWN": 101, "REINVESTMENT_POLICY": -5},
        )

    def test_percent_boundaries_are_allowed(self):
        """Verifies FR-02: 0 och 100 är giltiga procentsatser."""
        config = load_config(self.write(risk={"MAX_TOTAL_DRAWDOWN": 0, "REINVESTMENT_POLICY": 100}))
        self.assertEqual(config.risk.reinvestment_policy, Decimal("100"))

    def test_reserve_larger_than_start_capital(self):
        """Verifies ER-05: MINIMUM_RESERVE får inte vara större än START_CAPITAL."""
        self.assert_invalid(
            "MINIMUM_RESERVE (2000000) är större än START_CAPITAL (1000000)",
            risk={"MINIMUM_RESERVE": 2_000_000},
        )

    def test_missing_limit_in_sim_is_warning_and_blocked(self):
        """Verifies ER-02: i sim ger en saknad §25-gräns en varning och gränsen är None, aldrig obegränsad."""
        config = load_config(self.write(risk={"MAX_SINGLE_TRANSACTION": DROP}))
        self.assertIsNone(config.risk.max_single_transaction)
        self.assertEqual(config.risk.missing, ("MAX_SINGLE_TRANSACTION",))
        self.assertEqual(len(config.warnings), 1)
        self.assertIn("MAX_SINGLE_TRANSACTION saknas", config.warnings[0])

    def test_missing_limit_in_prod_is_error(self):
        """Verifies ER-02: i prod stoppar en saknad §25-gräns uppstart."""
        self.assert_invalid(
            "MAX_SINGLE_TRANSACTION saknas; i prod",
            system=PROD,
            risk={"currency": "SEK", "MAX_SINGLE_TRANSACTION": DROP},
        )

    def test_missing_limit_with_unknown_environment_is_error(self):
        """Verifies ER-02: okänd miljö behandlas strikt; en saknad gräns är då ett fel."""
        self.assert_invalid(
            "HUMAN_APPROVAL_THRESHOLD saknas",
            system={"environment": "test"},
            risk={"HUMAN_APPROVAL_THRESHOLD": DROP},
        )

    def test_unknown_key_is_error(self):
        """Verifies ER-02: ett stavfel får inte tyst stänga av en gräns; okända nycklar avvisas."""
        self.assert_invalid(
            "okänd nyckel 'MAX_SINGLE_TRANSACTON'",
            "okänd nyckel 'enviroment'",
            system={"enviroment": "sim"},
            risk={"MAX_SINGLE_TRANSACTON": 1},
        )


class TestSecrets(ConfigTestCase):
    def test_secret_keys_rejected_and_value_never_shown(self):
        """Verifies SR-10: *_KEY, *_TOKEN, *_SECRET och password i config/ avvisas utan att värdet visas."""
        value = "gsk-THIS-MUST-NOT-LEAK"
        error = self.assert_invalid(
            "GROQ_API_KEY ser ut som en hemlighet",
            "GITHUB_TOKEN ser ut som en hemlighet",
            "CLIENT_SECRET ser ut som en hemlighet",
            "password ser ut som en hemlighet",
            system={"GROQ_API_KEY": value, "password": value},
            risk={"GITHUB_TOKEN": value, "CLIENT_SECRET": value},
        )
        self.assertNotIn(value, str(error))
        self.assertNotIn("okänd nyckel 'GROQ_API_KEY'", str(error))  # rapporteras en gång, som hemlighet

    def test_secret_in_other_config_file_and_nested_table(self):
        """Verifies SR-10: hemligheter hittas i alla *.toml i config/, även i undertabeller."""
        self.assert_invalid(
            "providers.toml: groq.api_key ser ut som en hemlighet",
            providers__toml='[groq]\napi_key = "x"\n',
        )

    def test_env_file_in_config_dir_rejected(self):
        """Verifies SR-10: en .env-fil i config/ avvisas."""
        self.assert_invalid(".env: filer med hemligheter", __env="GROQ_API_KEY=x\n")


class TestFilesAndCollection(ConfigTestCase):
    def test_missing_file(self):
        """Verifies FR-02: en saknad konfigurationsfil stoppar uppstart."""
        self.assert_invalid("risk_limits.toml: filen saknas", risk=DROP)

    def test_missing_directory(self):
        """Verifies FR-02: en saknad konfigurationsmapp ger ConfigError, inte en krasch."""
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.dir / "finns-inte")
        self.assertIn("konfigurationsmappen finns inte", str(ctx.exception))

    def test_toml_syntax_error_is_reported(self):
        """Verifies FR-02: en trasig TOML-fil rapporteras som fel tillsammans med övriga fel."""
        self.write(system={"environment": DROP})
        (self.dir / "risk_limits.toml").write_text("START_CAPITAL = = 1\n", encoding="utf-8")
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.dir)
        joined = "\n".join(ctx.exception.errors)
        self.assertIn("risk_limits.toml: kan inte tolkas som TOML", joined)
        self.assertIn("environment saknas", joined)

    def test_all_errors_are_collected(self):
        """Verifies FR-02: alla fel samlas i ett meddelande, inte bara det första."""
        error = self.assert_invalid(
            "environment saknas",
            "är negativt",
            "ligger utanför 0–100",
            "okänd nyckel",
            "är större än START_CAPITAL",
            system={"environment": DROP},
            risk={
                "MAX_SINGLE_TRANSACTION": -1,
                "MAX_TOTAL_DRAWDOWN": 150,
                "MAX_BUDGET": 5,
                "MINIMUM_RESERVE": 5_000_000,
            },
        )
        self.assertGreaterEqual(len(error.errors), 5)
        self.assertTrue(str(error).startswith(f"Konfigurationen är ogiltig ({len(error.errors)} fel):"))

    def test_invalid_currency_does_not_hide_amount_errors(self):
        """Verifies FR-02: fel valuta döljer inte beloppsfel som reserv > kapital."""
        self.assert_invalid(
            "currency = 'SIM' är inte tillåtet i prod",
            "MINIMUM_RESERVE (3000000) är större än START_CAPITAL (1000000)",
            system={"environment": "prod", "base_currency": "SEK"},
            risk={"MINIMUM_RESERVE": 3_000_000},
        )


class TestCli(ConfigTestCase):
    def run_cli(self, *args):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        args = args or ("--config-dir", str(ROOT / "config"))
        # Arbetsmappen är testets temporära mapp, så att loggarna aldrig hamnar i repot.
        return subprocess.run(
            [sys.executable, "-m", "aie", "check-config", *args],
            cwd=self.dir,
            env=env,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    def test_cli_exit_0_with_default_config(self):
        """Verifies FR-02: `python -m aie check-config` ger kod 0 med standardkonfigurationen."""
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Konfiguration OK", result.stdout)

    def test_cli_exit_1_and_lists_all_errors(self):
        """Verifies FR-02: ogiltig konfiguration ger kod 1 och listar alla fel."""
        self.write(system={"environment": "prod"}, risk={"MAX_SINGLE_TRANSACTION": -1})
        result = self.run_cli("--config-dir", str(self.dir))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Konfiguration OK", result.stdout)
        for fragment in (
            "base_currency = 'SIM' är inte tillåtet i prod",
            "currency = 'SIM' är inte tillåtet i prod",
            "MAX_SINGLE_TRANSACTION = -1 är negativt",
        ):
            self.assertIn(fragment, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
