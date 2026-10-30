"""Evaluation Engine (ARCHITECTURE.md §2): incidentrapporter (FR-15), prognoslogg (FR-16),
lärdomsregister (FR-17), versionerade strategier (FR-18), prestationsmätning per roll (FR-19)
och avstängning bara på dokumenterade kriterier (SR-17)."""
from .forecasts import (
    Accuracy,
    Comparison,
    Forecast,
    ForecastError,
    ForecastLog,
    Outcome,
)
from .incidents import FIELDS, Incident, IncidentError, IncidentLog
from .lessons import CAUSES, STATUSES, Lesson, LessonError, LessonRegistry
from .performance import (
    PROFILES,
    Measure,
    PerformanceError,
    PerformanceReview,
    Review,
    Scorecard,
)
from .removal import CRITERIA, RemovalCase, RemovalError, RemovalReview
from .strategies import StrategyError, StrategyRegistry, Version

__all__ = [
    "CAUSES", "CRITERIA", "FIELDS", "PROFILES", "STATUSES",
    "Accuracy", "Comparison", "Forecast", "ForecastError", "ForecastLog", "Outcome",
    "Incident", "IncidentError", "IncidentLog",
    "Lesson", "LessonError", "LessonRegistry",
    "Measure", "PerformanceError", "PerformanceReview", "Review", "Scorecard",
    "RemovalCase", "RemovalError", "RemovalReview",
    "StrategyError", "StrategyRegistry", "Version",
]
