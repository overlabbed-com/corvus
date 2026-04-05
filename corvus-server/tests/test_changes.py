"""Tests for change window API."""

import pytest


@pytest.mark.asyncio
async def test_create_change(client):
    resp = await client.post(
        "/ops/changes",
        json={
            "targets": ["vllm-primary"],
            "description": "Deploying new model",
            "created_by": "claude-code",
            "rollback_plan": "Revert to previous image",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"].startswith("CHG-")
    assert data["status"] == "active"
    assert data["targets"] == ["vllm-primary"]
    assert data["expires_at"] is not None


@pytest.mark.asyncio
async def test_list_changes(client):
    await client.post(
        "/ops/changes",
        json={
            "targets": ["svc-a"],
            "description": "Test",
            "created_by": "test",
        },
    )
    resp = await client.get("/ops/changes")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_list_active_changes(client):
    resp = await client.get("/ops/changes/active")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_update_change(client):
    create = await client.post(
        "/ops/changes",
        json={
            "targets": ["svc-b"],
            "description": "Test",
            "created_by": "test",
        },
    )
    change_id = create.json()["id"]

    resp = await client.patch(
        f"/ops/changes/{change_id}",
        json={
            "status": "completed",
            "outcome": "success",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_update_change_not_found(client):
    resp = await client.patch("/ops/changes/CHG-NONEXIST", json={"status": "completed"})
    assert resp.status_code == 404
