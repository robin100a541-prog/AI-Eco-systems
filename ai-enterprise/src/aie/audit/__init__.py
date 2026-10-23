"""Audit System (ARCHITECTURE.md §2): append-only revisionslogg med hashkedja (SR-09)."""

from .log import GENESIS_HASH, AuditEntry, AuditLog, entry_hash

__all__ = ["GENESIS_HASH", "AuditEntry", "AuditLog", "entry_hash"]
