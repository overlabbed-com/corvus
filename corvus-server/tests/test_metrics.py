"""Tests for metrics and health endpoints."""

import pytest


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/ops/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_metrics(client):
    # Seed some data
    await client.post(
        "/ops/events",
        json={
            "source": "test",
            "type": "test.event",
            "target": "svc-a",
        },
    )
    await client.post(
        "/ops/incidents",
        json={
            "target": "svc-a",
            "title": "Test incident",
            "detected_by": "test",
        },
    )
    await client.post("/ops/cmdb/register", json={"name": "svc-a"})

    resp = await client.get("/ops/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "events_24h" in data
    assert "open_incidents" in data
    assert "total_services" in data
    assert "false_positive_rate" in data
    assert "gaps_by_workstream" in data


@pytest.mark.asyncio
async def test_metrics_includes_compliance_rate(client):
    """GET /ops/metrics includes compliance_rate."""
    # Create a change without events (gap)
    await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-a",
            "targets": ["svc-a"],
            "description": "No events change",
        },
    )

    # Create a change with events (compliant)
    resp = await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-b",
            "targets": ["svc-b"],
            "description": "Good change",
        },
    )
    change_id = resp.json()["id"]
    await client.post(
        "/ops/events",
        json={
            "source": "agent-b",
            "type": "change.started",
            "target": "svc-b",
            "related_change_id": change_id,
        },
    )

    resp = await client.get("/ops/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "compliance_rate" in data
    assert data["compliance_rate"] == 50.0


@pytest.mark.asyncio
async def test_compliance_endpoint_empty(client):
    """GET /ops/metrics/compliance returns full audit on empty DB."""
    resp = await client.get("/ops/metrics/compliance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["changes"]["total"] == 0
    assert data["incidents"]["total"] == 0
    assert data["compliance_rate"] == 100.0
    assert data["by_source"] == {}


@pytest.mark.asyncio
async def test_compliance_endpoint_with_gaps(client):
    """GET /ops/metrics/compliance returns detailed gap information."""
    # Create compliant change
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

    # Create non-compliant change
    await client.post(
        "/ops/changes",
        json={
            "created_by": "agent-b",
            "targets": ["svc-b"],
            "description": "Silent change",
        },
    )

    # Create non-compliant incident
    await client.post(
        "/ops/incidents",
        json={
            "target": "svc-c",
            "title": "Silent incident",
            "detected_by": "agent-c",
        },
    )

    resp = await client.get("/ops/metrics/compliance")
    assert resp.status_code == 200
    data = resp.json()

    assert data["changes"]["total"] == 2
    assert data["changes"]["covered"] == 1
    assert len(data["changes"]["uncovered"]) == 1

    assert data["incidents"]["total"] == 1
    assert data["incidents"]["covered"] == 0
    assert len(data["incidents"]["uncovered"]) == 1

    # 1 compliant out of 3 total (2 changes + 1 incident) => 33.3%
    assert data["compliance_rate"] == 33.3

    # Per-source breakdown
    assert "agent-a" in data["by_source"]
    assert data["by_source"]["agent-a"]["compliance_rate"] == 100.0
    assert "agent-b" in data["by_source"]
    assert data["by_source"]["agent-b"]["compliance_rate"] == 0.0
    # Incident source is also in by_source
    assert "agent-c" in data["by_source"]
    assert data["by_source"]["agent-c"]["compliance_rate"] == 0.0


@pytest.mark.asyncio
async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Corvus"
