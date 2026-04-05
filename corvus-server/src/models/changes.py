"""Change window models."""

from pydantic import BaseModel


class ChangeCreate(BaseModel):
    targets: list[str]
    description: str
    created_by: str
    rollback_plan: str | None = None
    project: str | None = None
    auto_expire: bool = True


class ChangeUpdate(BaseModel):
    status: str | None = None
    outcome: str | None = None


class ChangeResponse(BaseModel):
    id: str
    created_at: str
    created_by: str
    status: str
    targets: list[str]
    description: str
    rollback_plan: str | None = None
    project: str | None = None
    auto_expire: bool = True
    expires_at: str | None = None
    completed_at: str | None = None
    outcome: str | None = None
    authenticated_as: str | None = None
