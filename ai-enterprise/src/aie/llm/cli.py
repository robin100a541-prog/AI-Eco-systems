"""Kommandot `python -m aie manual` (D-005, Fas 3): grundarna besvarar förfrågningar till `manual`-providern.

    python -m aie manual list
    python -m aie manual show 3f2a9c0d1b4e5a67
    python -m aie manual answer 3f2a9c0d1b4e5a67 --as robin --file svar.txt   # eller --file - för stdin

`--as` måste vara en av `founders` i `config/system.toml` (D-021). Svar och nekade försök
skrivs till revisionsloggen, men aldrig själva texten. Kod 0 = lyckades, kod 1 = fel som är
utskrivet och loggat.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import runtime
from ..audit import AuditLog
from ..monitoring import get_logger
from .manual import ManualError, ManualInbox, manual_dir

log = get_logger("manual")


def manual(
    config_dir: Path,
    action: str,
    request_id: str | None = None,
    founder: str | None = None,
    answer_file: str | None = None,
) -> int:
    try:
        config = runtime._load(config_dir, console=False)
        inbox = ManualInbox(
            manual_dir(config.system.data_dir, config.system.environment)
        )
        if action == "list":
            return _list(inbox)
        if action == "show":
            return _show(inbox, request_id)
        with runtime._open(config) as db:
            audit = AuditLog(db)
            if founder not in config.system.founders:
                audit.append(
                    str(founder),
                    "manual.denied",
                    {"request_id": request_id, "reason": "inte grundare"},
                )
                return _error(
                    f"{founder!r} är inte grundare (founders i system.toml, D-021)"
                )
            try:
                text = _read(answer_file)
                inbox.answer(request_id, text, founder)
            except (ManualError, OSError) as exc:
                audit.append(
                    founder,
                    "manual.denied",
                    {"request_id": request_id, "reason": str(exc)},
                )
                return _error(str(exc))
            audit.append(
                founder,
                "manual.answered",
                {"request_id": request_id, "chars": len(text.strip())},
            )
            print(
                f"Svaret på {request_id} är sparat. Det används nästa gång uppgiften körs."
            )
            return 0
    except runtime.StartupError as exc:
        return runtime._fail(exc)


def _read(answer_file: str | None) -> str:
    if not answer_file:
        raise ManualError("ange svaret med --file <fil> eller --file - för stdin")
    if answer_file == "-":
        return sys.stdin.read()
    return Path(answer_file).read_text(encoding="utf-8")


def _list(inbox: ManualInbox) -> int:
    pending = inbox.pending()
    if not pending:
        print("Inga förfrågningar väntar på ett manuellt svar.")
        return 0
    print(f"{len(pending)} förfrågningar väntar på ett manuellt svar:")
    for r in pending:
        first = r.messages[-1][1].splitlines()[0] if r.messages else ""
        print(f"{r.request_id}  {r.created_at}  {first[:70]}")
    return 0


def _show(inbox: ManualInbox, request_id: str | None) -> int:
    try:
        request = inbox.get(request_id or "")
    except ManualError as exc:
        return _error(str(exc))
    if request is None:
        return _error(f"förfrågan {request_id} finns inte (eller är redan använd)")
    print(
        f"# Förfrågan {request.request_id} ({request.created_at}), högst {request.max_tokens} tokens"
    )
    print("# Kör texten nedan i Claude och spara svaret i en fil.\n")
    print(request.prompt())
    return 0


def _error(message: str) -> int:
    log.error("manual: %s", message)
    print(f"FEL: {message}", file=sys.stderr)
    return 1
