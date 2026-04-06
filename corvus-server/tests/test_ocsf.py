"""Tests for OCSF transformer."""

from src.ocsf import transform_to_ocsf


def test_transform_incident_opened():
    event = {
        "id": "EVT-001",
        "timestamp": "2026-03-29T18:10:01.412Z",
        "source": "ops-agent",
        "type": "incident.opened",
        "target": "vllm-primary",
        "severity": "critical",
        "data": {"summary": "CUDA OOM on vllm-primary"},
        "related_incident_id": "INC-042",
    }
    ocsf = transform_to_ocsf(event)

    assert ocsf["class_uid"] == 2005
    assert ocsf["class_name"] == "Incident Finding"
    assert ocsf["severity_id"] == 5
    assert ocsf["metadata"]["version"] == "1.3.0"
    assert ocsf["actor"]["agent"]["name"] == "ops-agent"
    assert ocsf["resources"][0]["uid"] == "vllm-primary"
    assert ocsf["unmapped"]["sop_event_type"] == "incident.opened"
    assert ocsf["finding_info"]["uid"] == "INC-042"


def test_transform_change_completed():
    event = {
        "id": "EVT-002",
        "timestamp": "2026-03-29T19:00:00Z",
        "source": "claude-code",
        "type": "change.completed",
        "target": "admin-api",
        "severity": "info",
        "data": {"summary": "Deployed v2"},
    }
    ocsf = transform_to_ocsf(event)

    assert ocsf["class_uid"] == 5019
    assert ocsf["activity_name"] == "Complete"


def test_transform_gap_event():
    event = {
        "id": "EVT-003",
        "type": "gap:coverage:no-runbook",
        "source": "corvus",
        "target": "unknown-svc",
        "severity": "warning",
        "data": {},
    }
    ocsf = transform_to_ocsf(event)

    assert ocsf["class_uid"] == 2003
    assert ocsf["class_name"] == "Compliance Finding"


def test_transform_unknown_type():
    event = {
        "id": "EVT-004",
        "type": "custom.unknown.type",
        "source": "agent-x",
        "target": "svc-a",
        "severity": "info",
        "data": {},
    }
    ocsf = transform_to_ocsf(event)

    # Should fallback to API Activity
    assert ocsf["class_uid"] == 6003
    assert ocsf["activity_name"] == "Other"
