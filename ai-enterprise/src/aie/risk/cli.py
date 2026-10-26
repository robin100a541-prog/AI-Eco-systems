"""Kommandot `python -m aie kill` (Fas 4e-2, SR-07, §38, D-030): nödstoppet.

    python -m aie kill status
    python -m aie kill engage --as yorgo --reason "okända transaktioner i ledgern"
    python -m aie kill release --as yorgo --reason "utrett: felaktig import, rättad"
    python -m aie kill release --as robin --reason "instämmer"

`--as` måste vara en av `founders` i `config/system.toml` (D-021). Återstarten följer processen
i `docs/operations.md`. Två olika grundare krävs, och revisionsloggen måste vara intakt. Kod 0
betyder att kommandot lyckades och kod 1 att ett fel skrevs ut och loggades.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import runtime
from ..agents import AgentRegistry
from ..audit import AuditLog
from ..authorization import load_permissions
from ..monitoring import get_logger
from .killswitch import KillSwitch, KillSwitchError

log = get_logger("kill")


def kill(config_dir: Path, action: str, founder: str | None, reason: str) -> int:
    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            permissions = load_permissions(config_dir)
            audit = AuditLog(db)
            switch = KillSwitch(db, AgentRegistry(permissions, db), permissions, audit,
                                frozenset(config.system.founders))
            if action == "status":
                return _print(switch.state())
            if founder not in config.system.founders:
                print(f"FEL: --as måste vara en av grundarna i system.toml: {', '.join(config.system.founders)}",
                      file=sys.stderr)
                return 1
            state = switch.engage(founder, reason) if action == "engage" else switch.vote_release(founder, reason)
            return _print(state)
    except runtime.StartupError as exc:
        return runtime._fail(exc)
    except KillSwitchError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        log.error("kill %s nekades: %s", action, exc)
        return 1


def _print(state) -> int:
    if not state.engaged:
        print("Nödstopp:       av")
        return 0
    print(f"Nödstopp:       AKTIVT sedan {state.engaged_at} ({state.engaged_by}: {state.reason})")
    print(f"Återstartsröster: {', '.join(state.release_votes) or 'inga'} (två olika grundare krävs, D-030)")
    return 0
