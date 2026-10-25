"""Ledgern (Fas 4a, §40): ekonomiskt register, idempotens, korrigeringsposter och resultatberäkning."""

from .ledger import (
    Approval,
    DuplicateEntry,
    Entry,
    EntryDraft,
    EntryType,
    Ledger,
    LedgerError,
    Status,
    StatusEvent,
)
from .results import Result, compute_result, recompute, result_for

__all__ = [
    "Approval",
    "DuplicateEntry",
    "Entry",
    "EntryDraft",
    "EntryType",
    "Ledger",
    "LedgerError",
    "Result",
    "Status",
    "StatusEvent",
    "compute_result",
    "recompute",
    "result_for",
]
