"""Tests for runbook API endpoints."""

from pathlib import Path

import pytest

from src.runbooks.loader import registry


@pytest.fixture(autouse=True)
def load_runbooks():
    """Load runbooks before each test."""
    runbook_dir = Path(__file__).parent.parent / "runbooks"
    if runbook_dir.exists() and not registry.list_all():
        registry.load_directory(runbook_dir)


@pytest.mark.asyncio
async def test_list_runbooks(client):
    resp = await client.get("/ops/runbooks")
    assert resp.status_code == 200
    runbooks = resp.json()
    assert len(runbooks) >= 3
    names = [r["name"] for r in runbooks]
    assert "Inference Service Triage" in names


@pytest.mark.asyncio
async def test_runbook_coverage(client):
    resp = await client.get("/ops/runbooks/coverage")
    assert resp.status_code == 200
    data = resp.json()
    assert "inference" in data["covered_service_types"]
    assert "database" in data["covered_service_types"]
    assert "proxy" in data["covered_service_types"]


@pytest.mark.asyncio
async def test_triage_with_service_type(client):
    resp = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "vllm-primary",
            "host": "tmtdockp01",
            "service_type": "inference",
            "investigation_data": {"logs": "CUDA error: out of memory"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "triaged"
    assert data["diagnosis"] == "gpu_oom"


@pytest.mark.asyncio
async def test_triage_no_runbook(client):
    resp = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "unknown-svc",
            "service_type": "nonexistent_type",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "no_runbook"
    assert "gap" in data["gap_pattern"]


@pytest.mark.asyncio
async def test_triage_from_cmdb_lookup(client):
    # Register a service first
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "test-db",
            "service_type": "database",
        },
    )

    resp = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "test-db",
            "investigation_data": {"logs": "disk full, no space left"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "triaged"
    assert data["service_type"] == "database"
    assert data["diagnosis"] == "disk_full"
