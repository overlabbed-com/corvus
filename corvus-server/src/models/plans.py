"""Plan execution models."""

from typing import Any

from pydantic import BaseModel


class PlanStepCreate(BaseModel):
    name: str
    description: str | None = None
    sequence: int
    depends_on: list[str] = []
    action_type: str
    targets: list[str]
    params: dict[str, Any] = {}
    failure_policy: str = "halt"  # halt / skip / retry
    max_retries: int = 0
    rollback: dict[str, Any] | None = None
    timeout: int = 300


class PlanCreate(BaseModel):
    title: str
    description: str | None = None
    steps: list[PlanStepCreate]
    created_by: str
    expires_hours: int = 24  # auto-expire approved plans (max 72)


class PlanApproveRequest(BaseModel):
    approved_by: str
    force: bool = False


class StepResultRequest(BaseModel):
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None


class PlanStepResponse(BaseModel):
    id: str
    plan_id: str
    name: str
    description: str | None = None
    sequence: int
    depends_on: list[str]
    action_type: str
    targets: list[str]
    params: dict[str, Any]
    failure_policy: str
    max_retries: int
    rollback: dict[str, Any] | None = None
    timeout: int
    status: str
    output: dict[str, Any] | None = None
    error: str | None = None
    executed_by: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    retry_count: int


class PlanResponse(BaseModel):
    id: str
    created_at: str
    created_by: str
    title: str
    description: str | None = None
    status: str
    targets: list[str]
    change_id: str | None = None
    approval_method: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    completed_at: str | None = None
    outcome: str | None = None
    expires_hours: int
    steps: list[PlanStepResponse] = []


class PlanStatusResponse(BaseModel):
    id: str
    status: str
    title: str
    change_id: str | None = None
    total_steps: int
    pending: int
    ready: int
    executing: int
    completed: int
    failed: int
    skipped: int
    rolled_back: int
    progress_pct: float
