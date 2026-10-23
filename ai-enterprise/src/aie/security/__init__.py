"""Säkerhet som inte hör till en enskild komponent: externt innehåll som opålitlig data (SR-06)."""
from .external import CLOSE_MARK, OPEN_MARK, ExternalContent, injection_signals

__all__ = ["CLOSE_MARK", "OPEN_MARK", "ExternalContent", "injection_signals"]
