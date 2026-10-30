"""Samarbete mellan agenter (Fas 3): samråd (FR-11). Oenighet och eskalering finns i governance (Robin)."""
from .consultation import (
    Consultation,
    ConsultationBoard,
    ConsultationError,
    Opinion,
    Position,
    Requirement,
    RiskClass,
    required_for,
)
from .opportunities import (
    KINDS,
    Opportunity,
    OpportunityError,
    OpportunityRegister,
    Step,
)

__all__ = [
    "KINDS",
    "Opportunity",
    "OpportunityError",
    "OpportunityRegister",
    "Step",
    "Consultation",
    "ConsultationBoard",
    "ConsultationError",
    "Opinion",
    "Position",
    "Requirement",
    "RiskClass",
    "required_for",
]
