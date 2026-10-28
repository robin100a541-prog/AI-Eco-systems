"""`python -m aie spend list|approve|reject` (F5, D-053): grundarnas godkännanden av enskilda utgifter.

    python -m aie spend list
    python -m aie spend approve 3 --as yorgo --note "annonsen är testad"
    python -m aie spend reject 4 --as robin --note "för dyrt"

Ett godkännande gäller i `VALID_DAYS` dagar, för samma departement, initiativ och högst samma belopp.
Det förbrukas när utgiften genomförs och kan aldrig användas igen. Alla andra gränser gäller ändå.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import runtime
from ..audit import AuditLog
from .approvals import VALID_DAYS, SpendApprovalError, SpendApprovals


def spend(config_dir: Path, action: str, approval_id: int | None = None, founder: str | None = None,
          note: str = "") -> int:
    try:
        config = runtime._load(config_dir, console=False)
        with runtime._open(config) as db:
            approvals = SpendApprovals(db, AuditLog(db), frozenset(config.system.founders))
            if action == "list":
                pending = approvals.pending()
                ready = approvals.approved_unused()
                if not pending and not ready:
                    print("Inga förfrågningar om utgifter.")
                for label, items in (("Väntar på en grundare", pending), (f"Godkända, oanvända (gäller {VALID_DAYS} dagar)", ready)):
                    if items:
                        print(f"{label}:")
                    for a in items:
                        print(f"  #{a.approval_id} {a.department}/{a.initiative}: högst {a.amount_minor} {a.currency}, "
                              f"av {a.requested_by}: {a.reason}")
                return 0
            try:
                result = (approvals.approve if action == "approve" else approvals.reject)(founder, approval_id, note)
            except SpendApprovalError as exc:
                print(f"FEL: {exc}", file=sys.stderr)
                return 1
            print(f"Förfrågan #{result.approval_id} är {result.status} av {result.decided_by}.")
            return 0
    except runtime.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1
