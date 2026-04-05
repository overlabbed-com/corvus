"""Tests for events API."""

import pytest


@pytest.mark.asyncio
async def test_emit_event(client):
    resp = await client.post(
        "/ops/events",
        json={
            "source": "test-agent",
            "type": "change.completed",
            "target": "admin-api",
            "severity": "info",
            "data": {"summary": "Deployed v2"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"].startswith("EVT-")
    assert data["type"] == "change.completed"


@pytest.mark.asyncio
async def test_list_events(client):
    await client.post(
        "/ops/events",
        json={
            "source": "test",
            "type": "test.event",
            "target": "svc-a",
        },
    )
    resp = await client.get("/ops/events")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_list_events_with_filters(client):
    await client.post(
        "/ops/events",
        json={
            "source": "agent-x",
            "type": "incident.opened",
            "target": "svc-z",
            "severity": "critical",
        },
    )
    resp = await client.get("/ops/events", params={"severity": "critical", "target": "svc-z"})
    assert resp.status_code == 200
    events = resp.json()
    assert all(e["severity"] == "critical" for e in events)


@pytest.mark.asyncio
async def test_get_context(client):
    await client.post(
        "/ops/events",
        json={
            "source": "test",
            "type": "test.event",
            "target": "svc-a",
            "severity": "warning",
        },
    )
    resp = await client.get("/ops/events/context")
    assert resp.status_code == 200
    data = resp.json()
    assert "events_24h" in data
    assert "active_incidents" in data
    assert "active_changes" in data
    assert "gaps" in data


@pytest.mark.asyncio
async def test_target_status_go(client):
    resp = await client.get("/ops/events/targets/clean-target/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recommendation"] == "GO"


@pytest.mark.asyncio
async def test_target_status_stop(client):
    # Create a critical incident
    await client.post(
        "/ops/incidents",
        json={
            "target": "troubled-svc",
            "title": "Critical failure",
            "severity": "critical",
            "detected_by": "test",
        },
    )
    resp = await client.get("/ops/events/targets/troubled-svc/status")
    data = resp.json()
    assert data["recommendation"] == "STOP"
    assert len(data["active_incidents"]) >= 1
