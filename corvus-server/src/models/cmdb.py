"""CMDB models."""

from typing import Any

from pydantic import BaseModel


class ServiceRegister(BaseModel):
    name: str
    host: str | None = None
    service_type: str | None = None
    critical: bool = False
    dependencies: list[str] = []
    registered_by: str | None = None


class ServiceUpdate(BaseModel):
    host: str | None = None
    service_type: str | None = None
    critical: bool | None = None
    dependencies: list[str] | None = None
    baseline_behavior: dict[str, Any] | None = None
    alert_policy: str | None = None


class BulkSyncItem(BaseModel):
    name: str
    host: str | None = None
    service_type: str | None = None
    critical: bool = False
    dependencies: list[str] = []


class BulkClassifyItem(BaseModel):
    name: str
    service_type: str


class BaselineBehavior(BaseModel):
    expected_restarts_per_day: int = 0
    expected_events: list[str] = []


class ServiceResponse(BaseModel):
    id: str
    name: str
    host: str | None = None
    service_type: str | None = None
    critical: bool = False
    dependencies: list[str] = []
    last_seen: str | None = None
    baseline_behavior: dict[str, Any] = {}
    alert_policy: str = "default"
    created_at: str
    registered_by: str | None = None
