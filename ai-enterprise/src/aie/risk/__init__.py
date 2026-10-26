"""Risk Engine (ARCHITECTURE.md §2): stop-loss (ER-13). Nödstopp och skyddat driftläge kommer i 4e-2 och 4e-3."""
from .stoploss import Breach, StopLoss, StopLossError, Trip

__all__ = ["Breach", "StopLoss", "StopLossError", "Trip"]
