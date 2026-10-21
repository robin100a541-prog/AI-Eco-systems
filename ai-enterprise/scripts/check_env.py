#!/usr/bin/env python3
"""Fas 0 miljökontroll för AI Enterprise System.

Kör:  python3 scripts/check_env.py --founder Yorgo
      (Windows: py scripts\\check_env.py --founder Robin)

Skriver en Markdown-rapport till stdout. Klistra in den i docs/environment.md.
Skriptet läser bara information — det installerar, ändrar eller skickar ingenting.
Det skriver aldrig ut värdet av hemligheter, bara om de är satta.

Endast standardbiblioteket används (beslut D-002).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

MIN_PYTHON = (3, 11)
MIN_FREE_DISK_GB = 2.0
LOCAL_MODEL_MIN_RAM_GB = 16.0  # grov tumregel för små lokala modeller; endast vägledande

OK, WARN, FAIL, INFO = "OK", "VARNING", "FEL", "INFO"


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class Report:
    founder: str
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str) -> None:
        self.checks.append(Check(name, status, detail))

    @property
    def blocking_failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]


def _run(cmd: list[str]) -> str | None:
    """Kör ett kommando och returnerar första raden av stdout, eller None."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, *cmd[1:]], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip()
    return text.splitlines()[0] if text else ""


def check_python(report: Report, version_info=sys.version_info) -> None:
    v = tuple(version_info[:2])
    detail = f"{version_info[0]}.{version_info[1]}.{version_info[2]} ({sys.executable})"
    report.add("Python ≥ 3.11", OK if v >= MIN_PYTHON else FAIL, detail)


def check_stdlib(report: Report) -> None:
    missing = []
    for mod in ("sqlite3", "tomllib", "decimal", "unittest", "hashlib", "uuid"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        report.add("Standardbibliotek", FAIL, "saknas: " + ", ".join(missing))
        return
    import sqlite3

    report.add("Standardbibliotek", OK, f"alla moduler finns, SQLite {sqlite3.sqlite_version}")


def check_git(report: Report, runner=_run) -> None:
    out = runner(["git", "--version"])
    if out is None:
        report.add("Git", FAIL, "hittas inte — installera från https://git-scm.com")
    else:
        report.add("Git", OK, out)


def check_disk(report: Report, path: str = ".", usage=shutil.disk_usage) -> None:
    free_gb = usage(path).free / 1024**3
    status = OK if free_gb >= MIN_FREE_DISK_GB else WARN
    report.add("Ledigt diskutrymme", status, f"{free_gb:.1f} GB")


def total_ram_gb() -> float | None:
    """Bästa försök att läsa totalt RAM utan tredjepartsbibliotek."""
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (ValueError, OSError):
        pass
    if sys.platform == "darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        if out and out.isdigit():
            return int(out) / 1024**3
    if sys.platform == "win32":
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return ms.ullTotalPhys / 1024**3
        except Exception:  # noqa: BLE001 — informativt, får aldrig krascha skriptet
            return None
    return None


def check_ram(report: Report, ram_gb: float | None) -> None:
    if ram_gb is None:
        report.add("RAM", INFO, "kunde inte avläsas")
        return
    note = (
        "räcker troligen för att utreda en liten lokal modell"
        if ram_gb >= LOCAL_MODEL_MIN_RAM_GB
        else "troligen för lite för lokal modell; använd rule/manual-provider"
    )
    report.add("RAM", INFO, f"{ram_gb:.1f} GB — {note}")


def check_api_key(report: Report, environ=os.environ) -> None:
    """ANTHROPIC_API_KEY gör att Claude Code debiterar API-pris i stället för Pro."""
    if environ.get("ANTHROPIC_API_KEY"):
        report.add(
            "ANTHROPIC_API_KEY",
            WARN,
            "är satt — Claude Code använder då betald API-fakturering i stället för Pro. "
            "Ta bort variabeln om ni inte uttryckligen beslutat om API-kostnad (D-005).",
        )
    else:
        report.add("ANTHROPIC_API_KEY", OK, "inte satt (Pro-abonnemanget används)")


def check_optional_tools(report: Report, runner=_run) -> None:
    for name, cmd, purpose in (
        ("Claude Code", ["claude", "--version"], "utvecklingsstöd, ingår i Pro"),
        ("Ollama", ["ollama", "--version"], "möjlig lokal modell (Q-06)"),
        ("GitHub CLI", ["gh", "--version"], "valfritt, förenklar PR-flödet"),
    ):
        out = runner(cmd)
        report.add(
            f"{name} (valfritt)",
            INFO,
            f"installerat: {out}" if out is not None else f"inte installerat — {purpose}",
        )


def build_report(founder: str) -> Report:
    report = Report(founder=founder)
    report.add("Operativsystem", INFO, f"{platform.system()} {platform.release()} ({platform.machine()})")
    check_python(report)
    check_stdlib(report)
    check_git(report)
    check_disk(report)
    check_ram(report, total_ram_gb())
    check_api_key(report)
    check_optional_tools(report)
    return report


def render_markdown(report: Report, now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now().astimezone()
    lines = [
        f"## Miljö: {report.founder}",
        "",
        f"Kontrollerad: {now.strftime('%Y-%m-%d %H:%M %Z')} med `scripts/check_env.py`",
        "",
        "| Kontroll | Status | Detalj |",
        "|---|---|---|",
    ]
    for c in report.checks:
        detail = c.detail.replace("|", "\\|")
        lines.append(f"| {c.name} | {c.status} | {detail} |")
    lines.append("")
    if report.blocking_failures:
        lines.append(
            "**Resultat: INTE REDO för Fas 1** — åtgärda: "
            + ", ".join(c.name for c in report.blocking_failures)
        )
    else:
        lines.append("**Resultat: REDO för Fas 1** (inga blockerande fel)")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fas 0 miljökontroll (läser bara, ändrar inget).")
    parser.add_argument("--founder", required=True, help="Ditt namn, t.ex. Yorgo eller Robin")
    args = parser.parse_args(argv)
    report = build_report(args.founder)
    sys.stdout.write(render_markdown(report))
    return 1 if report.blocking_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
