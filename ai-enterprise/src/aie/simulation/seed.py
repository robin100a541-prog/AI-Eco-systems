"""Testdata för kommandocentralen i SIM (dashboard D0b, D-073, FR-29).

Fyller en tom SIM-databas genom samma vägar som alltid, så att revisionskedjan är giltig:

1. Kör simuleringen (`simulate start`) med de deterministiska agenterna i `days` dagar.
2. Lägger exakt 3 väntande godkännanden via kärnans kö (`ApprovalQueue.submit_decision`): CEO skapar en
   uppgift, ger den till research-chefen, och research-chefen föreslår ett beslut över gränsen för
   mänskligt godkännande. Inget skrivs direkt i någon tabell.

Vägrar köra om miljön inte är `sim`, valutan inte är `SIM` eller databasen inte är SIM-databasen.
"""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path

from .. import runtime
from ..governance.cli import build as build_governance
from ..governance.decisions import DecisionDraft, RiskClass
from .cli import simulate
from .run import SimulationError, require_sim, stored_run

# Tre förslag till grundarna. Beloppen läggs ovanpå gränsen för mänskligt godkännande, i SIM.
PROPOSALS = (
    ("Test a second print-on-demand niche", "Plant posters for small apartments", 1_500, RiskClass.LOW),
    ("Buy a mockup template bundle", "Better product photos for all listings", 4_000, RiskClass.LOW),
    ("Run a two-week Pinterest promotion", "Paid pins for the five best-selling designs", 9_000, RiskClass.MEDIUM),
)


@dataclass(frozen=True, slots=True)
class SeedResult:
    database: Path
    days: int
    pending: int
    audit_ok: bool


def seed(config_dir: Path, *, days: int = 30, scenario: str = "normal", founder: str = "yorgo") -> SeedResult:
    """Fyller SIM-databasen. Kastar SimulationError om miljön inte är SIM eller databasen inte är tom."""
    try:
        config = runtime._load(config_dir, console=False)  # ER-15: SIM i prod är redan en ogiltig konfiguration
    except runtime.StartupError as exc:
        raise SimulationError(str(exc)) from exc
    require_sim(config)  # SR-11: före allt annat, så att ingen prod-databas ens öppnas
    with runtime._open(config) as db:
        if db.environment != "sim":
            raise SimulationError(f"databasen är {db.environment!r}, inte sim")
        if stored_run(db) is not None:
            raise SimulationError(f"{db.path} har redan en körning; ta bort den eller använd en annan datamapp")
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = simulate(config_dir, "start", scenario, founder, days)
    if code != 0:
        raise SimulationError("simuleringen misslyckades: " + out.getvalue().strip().splitlines()[-1])
    with runtime._open(config) as db:
        gov = build_governance(config, db, config_dir)
        limit = config.risk.human_approval_threshold
        threshold = limit.amount_minor if limit is not None else 0
        for title, why, extra, risk in PROPOSALS:
            task = gov.board.create("ceo-1", title, why)
            gov.board.assign("ceo-1", task.task_id, "lead-1")
            gov.queue.submit_decision("lead-1", task.task_id, DecisionDraft(
                chosen_action=title,
                reasoning=why,
                evidence=(f"simulated market, scenario {scenario}",),
                budget_minor=threshold + extra,
                risk_class=risk,
                expected_result="Measured against the forecast after 14 simulated days",
                stop_conditions="Stop if the net result is negative after 7 days",
                follow_up="Research lead reports in the daily report",
            ))
        pending = len(gov.queue.pending())
        return SeedResult(db.path, days, pending, gov.audit.verify().ok)
