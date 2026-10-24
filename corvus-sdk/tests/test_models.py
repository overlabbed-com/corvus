"""Tests for the response models — required fields, defaults and per-instance state."""

import pytest

import corvus_sdk
from corvus_sdk.models import (
    Change,
    Event,
    Incident,
    Problem,
    Service,
    StepResult,
    TriageResult,
)


def test_change_defaults_and_optionals():
    change = Change(
        id="CHG-1",
        created_at="2026-03-31T10:00:00",
        created_by="corvus-sdk",
        status="active",
        targets=["caddy"],
        description="Update Caddyfile",
    )
    assert (change.rollback_plan, change.project) == ("", "")
    assert change.expires_at is None
    assert change.completed_at is None
    assert change.outcome is None

    closed = Change(
        id="CHG-2",
        created_at="2026-03-31T10:00:00",
        created_by="ops",
        status="completed",
        targets=["vllm"],
        description="Restart",
        rollback_plan="restart --previous",
        project="inference",
        expires_at="2026-03-31T11:00:00",
        completed_at="2026-03-31T10:20:00",
        outcome="success",
    )
    assert closed.rollback_plan == "restart --previous"
    assert closed.completed_at == "2026-03-31T10:20:00"
    assert closed.outcome == "success"


def test_event_defaults_and_optionals():
    event = Event(
        id="EVT-1", timestamp="2026-03-31T10:00:00", source="corvus-sdk", type="change.started", target="caddy"
    )
    assert event.severity == "info"
    assert event.data == {}
    assert event.related_incident_id is None
    assert event.related_change_id is None

    linked = Event(
        id="EVT-2",
        timestamp="2026-03-31T10:00:00",
        source="corvus-sdk",
        type="incident.opened",
        target="vllm",
        severity="warning",
        data={"reason": "oom"},
        related_incident_id="INC-1",
        related_change_id="CHG-1",
    )
    assert linked.severity == "warning"
    assert linked.data == {"reason": "oom"}
    assert linked.related_incident_id == "INC-1"
    assert linked.related_change_id == "CHG-1"


def test_incident_defaults_and_optionals():
    incident = Incident(
        id="INC-1",
        created_at="2026-03-31T10:00:00",
        detected_by="corvus-sdk",
        target="vllm",
        status="open",
        severity="warning",
        title="GPU OOM",
    )
    assert incident.description is None
    assert incident.root_cause is None
    assert incident.remediation_applied is None
    assert incident.resolved_at is None
    assert incident.resolution_time_minutes is None

    resolved = Incident(
        id="INC-2",
        created_at="2026-03-31T10:00:00",
        detected_by="corvus-sdk",
        target="vllm",
        status="resolved",
        severity="critical",
        title="GPU OOM",
        description="VRAM exhausted",
        root_cause="kv-cache leak",
        remediation_applied="restart",
        resolved_at="2026-03-31T10:12:00",
        resolution_time_minutes=12,
    )
    assert resolved.root_cause == "kv-cache leak"
    assert resolved.remediation_applied == "restart"
    assert resolved.resolution_time_minutes == 12


def test_problem_defaults_and_optionals():
    problem = Problem(id="PRB-1", created_at="2026-03-31T10:00:00", status="identified", title="Recurring GPU OOM")
    assert problem.pattern is None
    assert problem.root_cause is None
    assert problem.workstream is None
    assert problem.severity == "medium"
    assert problem.correlated_incidents == []

    tracked = Problem(
        id="PRB-2",
        created_at="2026-03-31T10:00:00",
        status="in_progress",
        title="Config drift",
        pattern="caddy reloads weekly",
        root_cause="out-of-band edit",
        severity="high",
        correlated_incidents=["INC-1", "INC-2"],
        workstream="CI",
    )
    assert tracked.correlated_incidents == ["INC-1", "INC-2"]
    assert tracked.workstream == "CI"


def test_service_defaults_and_optionals():
    service = Service(id="SVC-1", name="caddy")
    assert service.host is None
    assert service.service_type is None
    assert service.critical is False
    assert service.dependencies == []
    assert service.baseline_behavior == {}
    assert service.alert_policy == "default"

    registered = Service(
        id="SVC-2",
        name="litellm",
        host="host-01",
        service_type="proxy",
        critical=True,
        dependencies=["postgresql"],
        baseline_behavior={"p99_ms": 120},
        alert_policy="strict",
    )
    assert registered.critical is True
    assert registered.dependencies == ["postgresql"]
    assert registered.alert_policy == "strict"


def test_step_result_carries_all_counters():
    step = StepResult(
        step_id="STEP-1",
        status="submitted",
        triage_id="TRG-1",
        all_steps_complete=False,
        total_steps=3,
        pending_steps=2,
    )
    assert step.step_id == "STEP-1"
    assert step.all_steps_complete is False
    assert (step.total_steps, step.pending_steps) == (3, 2)


def test_triage_result_defaults_and_optionals():
    triage = TriageResult(status="pending_steps", triage_id="TRG-1", target="caddy", service_type="proxy")
    assert triage.runbook_name is None
    assert triage.diagnosis is None
    assert triage.root_cause is None
    assert triage.confidence == 0.0
    assert triage.escalation_required is False
    assert triage.restart_safe is None
    assert triage.pending_steps == []

    completed = TriageResult(
        status="triaged",
        triage_id="TRG-2",
        target="vllm",
        service_type="inference",
        runbook_name="inference-oom.yaml",
        diagnosis="gpu_oom",
        root_cause="VRAM exhaustion",
        confidence=0.9,
        escalation_required=True,
        restart_safe=False,
        pending_steps=[{"id": "STEP-1"}],
    )
    assert completed.runbook_name == "inference-oom.yaml"
    assert completed.confidence == 0.9
    assert completed.escalation_required is True
    assert completed.restart_safe is False
    assert completed.pending_steps == [{"id": "STEP-1"}]


def test_required_fields_are_enforced():
    """A missing required field must raise, not silently default."""
    with pytest.raises(TypeError):
        Service(id="SVC-1")  # name is required
    with pytest.raises(TypeError):
        StepResult(step_id="STEP-1")  # status/triage_id/counters are required


def test_mutable_defaults_are_per_instance():
    """field(default_factory=...) must not hand every instance the same object."""
    event_a = Event(id="EVT-1", timestamp="t0", source="s", type="t", target="x")
    event_b = Event(id="EVT-2", timestamp="t0", source="s", type="t", target="x")
    event_a.data["leak"] = True
    assert event_b.data == {}

    service_a = Service(id="SVC-1", name="a")
    service_b = Service(id="SVC-2", name="b")
    service_a.dependencies.append("dep")
    service_a.baseline_behavior["cpu"] = 1
    assert service_b.dependencies == []
    assert service_b.baseline_behavior == {}

    problem_a = Problem(id="PRB-1", created_at="t0", status="open", title="a")
    problem_b = Problem(id="PRB-2", created_at="t0", status="open", title="b")
    problem_a.correlated_incidents.append("INC-1")
    assert problem_b.correlated_incidents == []

    triage_a = TriageResult(status="s", triage_id="TRG-1", target="x", service_type="y")
    triage_b = TriageResult(status="s", triage_id="TRG-2", target="x", service_type="y")
    triage_a.pending_steps.append({"id": "STEP-1"})
    assert triage_b.pending_steps == []


def test_public_surface_is_reexported():
    assert set(corvus_sdk.__all__) == {
        "CorvusClient",
        "CorvusError",
        "Change",
        "Event",
        "Incident",
        "Problem",
        "Service",
        "StepResult",
        "TriageResult",
    }
    assert corvus_sdk.Change is Change
    assert corvus_sdk.TriageResult is TriageResult
    assert corvus_sdk.__version__ == "0.1.0"
