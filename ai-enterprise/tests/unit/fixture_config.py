"""Fast testkonfiguration (D-047).

Tester som räknar med bestämda belopp ska inte gå sönder när grundarna ändrar gränserna i `config/`.
`TEST_CONFIG` är en kopia av repots `config/` där `risk_limits.toml` och `budgets.toml` byts mot de låsta
testvärdena i `tests/fixtures/limits/`: startkapital 1 000 000 SIM och fasta budgetar enligt D-026.
Allt annat (behörigheter, skatt, scenarier) är repots egna filer. Samma kod finns i
`tests/acceptance/fixture_config.py`.
"""
import atexit
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXED_LIMITS = ROOT / "tests" / "fixtures" / "limits"


def _build() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="aie-test-config-"))
    atexit.register(shutil.rmtree, tmp, True)
    config = tmp / "config"
    shutil.copytree(ROOT / "config", config)
    for name in ("risk_limits.toml", "budgets.toml"):
        shutil.copy(FIXED_LIMITS / name, config / name)
    return config


TEST_CONFIG = _build()
