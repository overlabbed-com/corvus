"""Data models for Corvus API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Change:
    """A change window."""

    id: str
    created_at: str
    created_by: str
    status: str
    targets: list[str]
    description: str
    rollback_plan: str = ""
    project: str = ""
    expires_at: str | None = None
    completed_at: str | None = None
    outcome: str | None = None


@dataclass
class Event:
    """An operational event."""

    id: str
    timestamp: str
    source: str
    type: str
    target: str
    severity: str = "info"
    data: dict[str, Any] = field(default_factory=dict)
    related_incident_id: str | None = None
    related_change_id: str | None = None


@dataclass
class Incident:
    """An operational incident."""

    id: str
    created_at: str
    detected_by: str
    target: str
    status: str
    severity: str
    title: str
    description: str | None = None
    root_cause: str | None = None
    remediation_applied: str | None = None
    resolved_at: str | None = None
    resolution_time_minutes: int | None = None


@dataclass
class Problem:
    """A recurring problem pattern."""

    id: str
    created_at: str
    status: str
    title: str
    pattern: str | None = None
    root_cause: str | None = None
    severity: str = "medium"
    correlated_incidents: list[str] = field(default_factory=list)
    workstream: str | None = None


@dataclass
class Service:
    """A CMDB service entry."""

    id: str
    name: str
    host: str | None = None
    service_type: str | None = None
    critical: bool = False
    dependencies: list[str] = field(default_factory=list)
    baseline_behavior: dict[str, Any] = field(default_factory=dict)
    alert_policy: str = "default"


@dataclass
class StepResult:
    """Result of submitting a step execution."""

    step_id: str
    status: str
    triage_id: str
    all_steps_complete: bool
    total_steps: int
    pending_steps: int


@dataclass
class TriageResult:
    """Result of a triage run."""

    status: str
    triage_id: str
    target: str
    service_type: str
    runbook_name: str | None = None
    diagnosis: str | None = None
    root_cause: str | None = None
    confidence: float = 0.0
    escalation_required: bool = False
    restart_safe: bool | None = None
    pending_steps: list[dict[str, Any]] = field(default_factory=list)
