"""Problem models."""

from pydantic import BaseModel


class ProblemCreate(BaseModel):
    title: str
    pattern: str | None = None
    root_cause: str | None = None
    recommended_fix: str | None = None
    workaround: str | None = None
    severity: str = "medium"
    workstream: str | None = None


class ProblemUpdate(BaseModel):
    status: str | None = None
    root_cause: str | None = None
    recommended_fix: str | None = None
    workaround: str | None = None
    assigned_to: str | None = None
    workstream: str | None = None


class ProblemCorrelate(BaseModel):
    incident_id: str
    problem_id: str


class ProblemResponse(BaseModel):
    id: str
    created_at: str
    status: str
    title: str
    pattern: str | None = None
    root_cause: str | None = None
    recommended_fix: str | None = None
    workaround: str | None = None
    correlated_incidents: list[str] = []
    workstream: str | None = None
    severity: str
    assigned_to: str | None = None
