"""Tests for compliance audit logic."""

import pytest

from src.database import get_db
from src.tasks.compliance_audit import run_compliance_audit


@pytest.mark.asyncio
async def test_compliance_audit_empty_db(client):
    """Compliance audit on empty DB returns zero counts."""
    db = await get_db()
    try:
        result = await run_compliance_audit(db)
    finally:
        await db.close()

    assert result["changes"]["total"] == 0
    assert result["changes"]["covered"] == 0
    assert result["changes"]["uncovered"] == []
    assert result["incidents"]["total"] == 0
    assert result["incidents"]["covered"] == 0
    assert result["incidents"]["uncovered"] == []
    assert result["compliance_rate"] == 100.0  # No items = fully compliant
    assert result["by_source"] == {}


@pytest.mark.asyncio
async def test_compliance_audit_compliant_change(client):
    """A change with matching events is compliant."""
    # Create a change
    resp = await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-a",
            "targets": ["svc-a"],
            "description": "Update config",
        },
    )
    change_id = resp.json()["id"]

    # Emit an event referencing the change
    await client.post(
        "/ops/events",
        json={
            "source": "agent-a",
            "type": "change.started",
            "target": "svc-a",
            "related_change_id": change_id,
        },
    )

    db = await get_db()
    try:
        result = await run_compliance_audit(db)
    finally:
        await db.close()

    assert result["changes"]["total"] == 1
    assert result["changes"]["covered"] == 1
    assert result["changes"]["uncovered"] == []
    assert result["compliance_rate"] == 100.0


@pytest.mark.asyncio
async def test_compliance_audit_non_compliant_change(client):
    """A change without any matching events is a gap."""
    # Create a change with no events
    await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-a",
            "targets": ["svc-a"],
            "description": "Silent change",
        },
    )

    db = await get_db()
    try:
        result = await run_compliance_audit(db)
    finally:
        await db.close()

    assert result["changes"]["total"] == 1
    assert result["changes"]["covered"] == 0
    assert result["compliance_rate"] == 0.0
    assert len(result["changes"]["uncovered"]) == 1
    assert result["changes"]["uncovered"][0]["type"] == "change_without_event"


@pytest.mark.asyncio
async def test_compliance_audit_incident_without_event(client):
    """An incident without related events is a gap."""
    # Create an incident with no events
    await client.post(
        "/ops/incidents",
        json={
            "target": "svc-b",
            "title": "Silent incident",
            "detected_by": "agent-b",
        },
    )

    db = await get_db()
    try:
        result = await run_compliance_audit(db)
    finally:
        await db.close()

    assert result["incidents"]["total"] == 1
    assert result["incidents"]["covered"] == 0
    assert len(result["incidents"]["uncovered"]) == 1
    assert result["incidents"]["uncovered"][0]["type"] == "incident_without_event"
    # One incident uncovered => 0% compliance
    assert result["compliance_rate"] == 0.0


@pytest.mark.asyncio
async def test_compliance_audit_mixed(client):
    """Mix of compliant and non-compliant items."""
    # Compliant change (has matching event)
    resp = await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-a",
            "targets": ["svc-a"],
            "description": "Good change",
        },
    )
    change_id = resp.json()["id"]
    await client.post(
        "/ops/events",
        json={
            "source": "agent-a",
            "type": "change.started",
            "target": "svc-a",
            "related_change_id": change_id,
        },
    )

    # Non-compliant change (no events)
    await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-b",
            "targets": ["svc-b"],
            "description": "Bad change",
        },
    )

    db = await get_db()
    try:
        result = await run_compliance_audit(db)
    finally:
        await db.close()

    assert result["changes"]["total"] == 2
    assert result["changes"]["covered"] == 1
    assert result["compliance_rate"] == 50.0


@pytest.mark.asyncio
async def test_compliance_audit_per_source_breakdown(client):
    """Audit provides per-source breakdown including incidents."""
    # Agent-a creates a compliant change
    resp = await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-a",
            "targets": ["svc-a"],
            "description": "Good change",
        },
    )
    change_id = resp.json()["id"]
    await client.post(
        "/ops/events",
        json={
            "source": "agent-a",
            "type": "change.started",
            "target": "svc-a",
            "related_change_id": change_id,
        },
    )

    # Agent-b creates a non-compliant change
    await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-b",
            "targets": ["svc-b"],
            "description": "Bad change",
        },
    )

    db = await get_db()
    try:
        result = await run_compliance_audit(db)
    finally:
        await db.close()

    by_source = result["by_source"]
    assert "agent-a" in by_source
    assert by_source["agent-a"]["compliance_rate"] == 100.0
    assert "agent-b" in by_source
    assert by_source["agent-b"]["compliance_rate"] == 0.0


@pytest.mark.asyncio
async def test_compliance_audit_incidents_in_by_source(client):
    """Incidents are included in the per-source breakdown."""
    # Agent-c detects an incident without events
    await client.post(
        "/ops/incidents",
        json={
            "target": "svc-c",
            "title": "Silent incident",
            "detected_by": "agent-c",
        },
    )

    db = await get_db()
    try:
        result = await run_compliance_audit(db)
    finally:
        await db.close()

    assert "agent-c" in result["by_source"]
    assert result["by_source"]["agent-c"]["total"] == 1
    assert result["by_source"]["agent-c"]["compliant"] == 0
    assert result["by_source"]["agent-c"]["compliance_rate"] == 0.0


@pytest.mark.asyncio
async def test_compliance_audit_incidents_in_compliance_rate(client):
    """compliance_rate denominator includes both changes and incidents."""
    # 1 compliant change
    resp = await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-a",
            "targets": ["svc-a"],
            "description": "Good change",
        },
    )
    change_id = resp.json()["id"]
    await client.post(
        "/ops/events",
        json={
            "source": "agent-a",
            "type": "change.started",
            "target": "svc-a",
            "related_change_id": change_id,
        },
    )

    # 1 uncovered incident
    await client.post(
        "/ops/incidents",
        json={
            "target": "svc-b",
            "title": "Silent incident",
            "detected_by": "agent-b",
        },
    )

    db = await get_db()
    try:
        result = await run_compliance_audit(db)
    finally:
        await db.close()

    # 1 compliant out of 2 total => 50%
    assert result["compliance_rate"] == 50.0
