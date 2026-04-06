"""Tests for incidents API."""

import pytest


@pytest.mark.asyncio
async def test_create_incident(client):
    resp = await client.post(
        "/ops/incidents",
        json={
            "target": "vllm-primary",
            "title": "CUDA OOM",
            "description": "GPU VRAM exhausted",
            "severity": "critical",
            "detected_by": "ops-agent:health_sweep",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"].startswith("INC-")
    assert data["status"] == "open"
    assert data["severity"] == "critical"


@pytest.mark.asyncio
async def test_list_incidents(client):
    await client.post(
        "/ops/incidents",
        json={
            "target": "svc-a",
            "title": "Test",
            "detected_by": "test",
        },
    )
    resp = await client.get("/ops/incidents")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_incident(client):
    create = await client.post(
        "/ops/incidents",
        json={
            "target": "svc-a",
            "title": "Test",
            "detected_by": "test",
        },
    )
    incident_id = create.json()["id"]
    resp = await client.get(f"/ops/incidents/{incident_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == incident_id


@pytest.mark.asyncio
async def test_get_incident_not_found(client):
    resp = await client.get("/ops/incidents/INC-NONEXIST")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resolve_incident(client):
    create = await client.post(
        "/ops/incidents",
        json={
            "target": "svc-a",
            "title": "Test",
            "detected_by": "test",
        },
    )
    incident_id = create.json()["id"]

    resp = await client.patch(
        f"/ops/incidents/{incident_id}",
        json={
            "status": "resolved",
            "root_cause": "Memory leak",
            "remediation_applied": "Restarted container",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resolved"
    assert data["resolved_at"] is not None
    assert data["resolution_time_minutes"] is not None
