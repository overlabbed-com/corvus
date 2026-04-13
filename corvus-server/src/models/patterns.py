"""Pattern quality models."""

from typing import Any

from pydantic import BaseModel, Field


class Pattern(BaseModel):
    """Triage pattern definition."""
    id: str
    name: str
    pattern_type: str  # runbook, manual, learned
    source: str  # runbook name, incident ID, etc.
    trigger_conditions: dict[str, Any]
    diagnosis: str
    avg_confidence: float = 0.0
    usage_count: int = 0
    success_count: int = 0
    last_used_at: str | None = None
    quality_score: float = 0.0
    created_at: str
    updated_at: str


class PatternMetrics(BaseModel):
    """Pattern quality metrics."""
    pattern_id: str
    name: str
    accuracy: float = 0.0  # % successful resolutions
    confidence_accuracy: float = 0.0  # 1 - |predicted - actual|
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_resolution_time_minutes: float | None = None
    last_used_at: str | None = None
    quality_score: float = 0.0
    recency_score: float = 0.0
    coverage_score: float = 0.0


class PatternFeedback(BaseModel):
    """Feedback on pattern outcome."""
    pattern_id: str
    success: bool  # Did this diagnosis lead to resolution?
    resolution_time_minutes: float | None = None
    notes: str | None = None


class PatternQualityResponse(BaseModel):
    """Pattern with quality metrics."""
    pattern: Pattern
    metrics: PatternMetrics


class TopPatternsResponse(BaseModel):
    """List of top patterns."""
    patterns: list[PatternQualityResponse]
    total_count: int
