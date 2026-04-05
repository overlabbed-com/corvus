"""Incident models."""

from pydantic import BaseModel


class IncidentCreate(BaseModel):
    target: str
    title: str
    description: str | None = None
    severity: str = "medium"
    detected_by: str = "unknown"


class IncidentUpdate(BaseModel):
    status: str | None = None
    severity: str | None = None
    root_cause: str | None = None
    investigation_summary: str | None = None
    remediation_applied: str | None = None
    correlated_to_problem: str | None = None


class IncidentResponse(BaseModel):
    id: str
    created_at: str
    detected_by: str
    target: str
    status: str
    severity: str
    title: str
    description: str | None = None
    root_cause: str | None = None
    investigation_summary: str | None = None
    remediation_applied: str | None = None
    resolved_at: str | None = None
    resolution_time_minutes: int | None = None
    correlated_to_problem: str | None = None
    authenticated_as: str | None = None
