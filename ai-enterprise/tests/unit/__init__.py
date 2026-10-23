# Gör paketet i src/ importerbart utan installation (docs/setup.md).
# `python -m unittest discover -s tests` importerar det här paketet före testmodulerna,
# och pathlib ger rätt sökväg på Windows, macOS och Linux.
import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
