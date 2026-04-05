"""Tests for triage feedback loop (issue #4)."""

import pytest

from tests.conftest import client  # noqa: F401


@pytest.mark.asyncio
async def test_triage_creates_log_entry(client):
    """POST /ops/runbooks/triage should persist a triage log entry."""
    # Register a service in CMDB first
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "vllm-primary",
            "host": "dockp04",
            "service_type": "inference",
            "critical": True,
        },
    )

    # Run triage
    resp = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "vllm-primary",
            "service_type": "inference",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "triage_id" in data

    # Verify log entry exists
    resp = await client.get("/ops/triage")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) >= 1
    assert entries[0]["target"] == "vllm-primary"
    assert entries[0]["service_type"] == "inference"
    assert entries[0]["outcome"] == "pending"


@pytest.mark.asyncio
async def test_triage_outcome_success(client):
    """PATCH /ops/triage/{id} should record outcome."""
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "vllm-primary",
            "host": "dockp04",
            "service_type": "inference",
            "critical": True,
        },
    )

    resp = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "vllm-primary",
            "service_type": "inference",
        },
    )
    triage_id = resp.json()["triage_id"]

    # Record success
    resp = await client.patch(
        f"/ops/triage/{triage_id}",
        json={
            "outcome": "success",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "success"
    assert data["resolution_time_minutes"] is not None


@pytest.mark.asyncio
async def test_triage_outcome_failure(client):
    """PATCH /ops/triage/{id} with failure should record correctly."""
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "redis-primary",
            "host": "dockp04",
            "service_type": "database",
            "critical": True,
        },
    )

    resp = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "redis-primary",
            "service_type": "database",
        },
    )
    triage_id = resp.json()["triage_id"]

    resp = await client.patch(
        f"/ops/triage/{triage_id}",
        json={
            "outcome": "failure",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "failure"


@pytest.mark.asyncio
async def test_triage_list_filters(client):
    """GET /ops/triage should support filters."""
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "vllm-primary",
            "host": "dockp04",
            "service_type": "inference",
            "critical": True,
        },
    )

    await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "vllm-primary",
            "service_type": "inference",
        },
    )

    # Filter by service_type
    resp = await client.get("/ops/triage", params={"service_type": "inference"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Filter by nonexistent service_type
    resp = await client.get("/ops/triage", params={"service_type": "nonexistent"})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_triage_no_runbook_still_logs(client):
    """Triage with no matching runbook should still create a log entry."""
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "custom-svc",
            "host": "dockp04",
            "service_type": "custom_type",
        },
    )

    resp = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "custom-svc",
            "service_type": "custom_type",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "no_runbook"
    # Should still have triage_id for tracking
    assert "triage_id" in data


@pytest.mark.asyncio
async def test_metrics_include_triage_stats(client):
    """GET /ops/metrics should include triage effectiveness stats."""
    resp = await client.get("/ops/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "runbook_hit_rate" in data
    assert "escalation_rate_by_runbook" in data
    assert "avg_resolution_time_by_service_type" in data


@pytest.mark.asyncio
async def test_triage_patch_nonexistent_returns_404(client):
    """PATCH /ops/triage/TRG-NONEXISTENT should return 404."""
    resp = await client.patch(
        "/ops/triage/TRG-NONEXISTENT",
        json={"outcome": "success"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Triage entry not found"


@pytest.mark.asyncio
async def test_triage_re_patch_returns_409(client):
    """PATCH /ops/triage/{id} twice should return 409 on second attempt."""
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "redis-dup",
            "host": "dockp04",
            "service_type": "database",
            "critical": True,
        },
    )

    resp = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "redis-dup",
            "service_type": "database",
        },
    )
    triage_id = resp.json()["triage_id"]

    # First patch — should succeed
    resp = await client.patch(
        f"/ops/triage/{triage_id}",
        json={"outcome": "success"},
    )
    assert resp.status_code == 200

    # Second patch — should be rejected
    resp = await client.patch(
        f"/ops/triage/{triage_id}",
        json={"outcome": "failure"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Outcome already recorded"


@pytest.mark.asyncio
async def test_metrics_runbook_hit_rate(client):
    """Runbook hit rate should reflect diagnosis confidence."""
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "vllm-primary",
            "host": "dockp04",
            "service_type": "inference",
            "critical": True,
        },
    )

    # Run triage (will produce a result with some confidence)
    await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "vllm-primary",
            "service_type": "inference",
        },
    )

    resp = await client.get("/ops/metrics")
    data = resp.json()
    # Should have a numeric hit rate
    assert isinstance(data["runbook_hit_rate"], (int, float))
