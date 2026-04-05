"""Tests for CMDB API."""

import pytest


@pytest.mark.asyncio
async def test_register_service(client):
    resp = await client.post(
        "/ops/cmdb/register",
        json={
            "name": "vllm-primary",
            "host": "tmtdockp01",
            "service_type": "inference",
            "critical": True,
            "dependencies": ["nfs-models"],
            "registered_by": "nemoclaw",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "vllm-primary"
    assert data["service_type"] == "inference"
    assert data["critical"] is True


@pytest.mark.asyncio
async def test_register_service_upsert(client):
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "svc-upsert",
            "host": "host1",
        },
    )
    resp = await client.post(
        "/ops/cmdb/register",
        json={
            "name": "svc-upsert",
            "host": "host2",
            "service_type": "utility",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["host"] == "host2"
    assert resp.json()["service_type"] == "utility"


@pytest.mark.asyncio
async def test_list_services(client):
    await client.post("/ops/cmdb/register", json={"name": "svc-list-test"})
    resp = await client.get("/ops/cmdb")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_service(client):
    await client.post("/ops/cmdb/register", json={"name": "svc-get-test"})
    resp = await client.get("/ops/cmdb/svc-get-test")
    assert resp.status_code == 200
    assert resp.json()["name"] == "svc-get-test"


@pytest.mark.asyncio
async def test_get_service_not_found(client):
    resp = await client.get("/ops/cmdb/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_service(client):
    await client.post("/ops/cmdb/register", json={"name": "svc-update"})
    resp = await client.patch(
        "/ops/cmdb/svc-update",
        json={
            "service_type": "database",
            "baseline_behavior": {"expected_restarts_per_day": 0},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["service_type"] == "database"
    assert resp.json()["baseline_behavior"]["expected_restarts_per_day"] == 0


@pytest.mark.asyncio
async def test_bulk_sync(client):
    resp = await client.post(
        "/ops/cmdb/bulk-sync",
        json=[
            {"name": "svc-bulk-1", "host": "host1", "service_type": "utility"},
            {"name": "svc-bulk-2", "host": "host2", "service_type": "proxy"},
        ],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2


@pytest.mark.asyncio
async def test_bulk_classify(client):
    await client.post("/ops/cmdb/register", json={"name": "svc-classify"})
    resp = await client.post(
        "/ops/cmdb/bulk-classify",
        json=[
            {"name": "svc-classify", "service_type": "inference"},
        ],
    )
    assert resp.status_code == 200
    assert resp.json()["classified"] == 1
