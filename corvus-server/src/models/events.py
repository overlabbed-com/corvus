"""Event models."""

from typing import Any

from pydantic import BaseModel


class EventCreate(BaseModel):
    source: str
    type: str
    target: str
    severity: str = "info"
    data: dict[str, Any] = {}
    related_incident_id: str | None = None
    related_change_id: str | None = None
    related_problem_id: str | None = None
    parent_event_id: str | None = None


class EventResponse(BaseModel):
    id: str
    timestamp: str
    source: str
    type: str
    target: str
    severity: str
    data: dict[str, Any]
    related_incident_id: str | None = None
    related_change_id: str | None = None
    related_problem_id: str | None = None
    parent_event_id: str | None = None
    authenticated_as: str | None = None


class TargetStatus(BaseModel):
    target: str
    recommendation: str  # GO, CAUTION, STOP
    reason: str
    active_changes: list[dict[str, Any]] = []
    active_incidents: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []
    trust_tier: str = "ESCALATE"
