"""Exercise two separate daily CLI processes with temporary SIM data and no credentials.

This is a deployment smoke check, not a production run. No cache, remote models,
repository changes, live databases or publication are involved.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aie.audit import AuditLog
from aie.config import load_config
from aie.memory import Database


def main() -> None:
    config = load_config(ROOT / "config")
    if config.system.environment != "sim" or config.risk.currency != "SIM":
        raise ValueError("verification requires sim/SIM configuration")
    # Deliberately do not inherit API keys, GitHub tokens or other service credentials.
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP") if key in os.environ}
    env["PYTHONPATH"] = str(ROOT / "src")
    with tempfile.TemporaryDirectory(prefix="aie-deployment-check-") as folder:
        work = Path(folder)
        cfg, data, logs = work / "config", work / "data", work / "logs"
        shutil.copytree(ROOT / "config", cfg)
        path = cfg / "system.toml"
        text = path.read_text(encoding="utf-8")
        for key, value in (("data_dir", data), ("log_dir", logs)):
            text = re.sub(rf'(?m)^{key} = .*$', lambda m: f'{key} = {json.dumps(str(value))}', text)
        path.write_text(text, encoding="utf-8")
        reports, dashboard = work / "reports", work / "dashboard" / "status.json"
        command = [sys.executable, "-m", "aie", "daily-cycle", "--config-dir", str(cfg),
                   "--as", sorted(config.system.founders)[0], "--agents", "scripted", "--out", str(reports),
                   "--dashboard", str(dashboard), "--questions", str(work / "questions.md"),
                   "--kill-file", str(work / "KILL-SWITCH")]
        for n in (1, 2):
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
            if result.returncode:
                raise RuntimeError(f"daily process {n} failed:\n{result.stdout}\n{result.stderr}")
            print(f"daily process {n}: OK (scripted, isolated SIM)")
        with Database.open(data, "sim") as db:
            days = db.connection.execute("SELECT day, date FROM simulation_days ORDER BY day").fetchall()
            if [day for day, _ in days] != [1, 2]:
                raise AssertionError(f"restart did not resume correctly: {days}")
            if not AuditLog(db).verify().ok:
                raise AssertionError("audit chain failed")
            if db.connection.execute("SELECT DISTINCT currency FROM ledger_entries").fetchall() != [("SIM",)]:
                raise AssertionError("currency isolation failed")
        for _, day in days:
            if not (reports / "daily" / f"{day}.md").is_file():
                raise AssertionError(f"daily report missing for {day}")
        status = json.loads(dashboard.read_text(encoding="utf-8"))
        if status["classification"] != "public" or status["scoreboard"]["real"] is not None:
            raise AssertionError("dashboard classification/currency isolation failed")
        print("PASS: two resumed days, both reports, public SIM dashboard and intact audit; no working state changed")


if __name__ == "__main__":
    main()
