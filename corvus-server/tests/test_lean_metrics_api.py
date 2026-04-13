"""Lean metrics API tests."""

import pytest

from src.tasks.metrics_collector import store_snapshot


@pytest.mark.asyncio
async def test_get_current_metrics(client):
    """GET /ops/lean-metrics returns latest snapshot per tier."""
    await store_snapshot("value_stream", {"incident_cycle_time": {"p50": 120, "count": 5}})
    await store_snapshot("throughput", {"wip": 3})
    resp = await client.get("/ops/lean-metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "value_stream" in data
    assert "throughput" in data


@pytest.mark.asyncio
async def test_get_history(client):
    """GET /ops/lean-metrics/history returns time series."""
    await store_snapshot("value_stream", {"test": 1})
    await store_snapshot("value_stream", {"test": 2})
    resp = await client.get("/ops/lean-metrics/history?hours=1&tier=value_stream")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


@pytest.mark.asyncio
async def test_get_throughput(client):
    """GET /ops/lean-metrics/throughput returns bucketed counts."""
    resp = await client.get("/ops/lean-metrics/throughput?entity=incidents&hours=168")
    assert resp.status_code == 200
    data = resp.json()
    assert "buckets" in data


@pytest.mark.asyncio
async def test_get_bottlenecks(client):
    """GET /ops/lean-metrics/bottlenecks returns ranked list."""
    # Store a baseline and a recent snapshot
    await store_snapshot("value_stream", {"incident_cycle_time": {"p50": 100, "p95": 200, "p99": 300, "count": 10}})
    resp = await client.get("/ops/lean-metrics/bottlenecks")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_adjustments(client):
    """GET /ops/lean-metrics/adjustments returns audit trail."""
    resp = await client.get("/ops/lean-metrics/adjustments")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_convergence(client):
    """GET /ops/lean-metrics/convergence returns per-parameter status."""
    resp = await client.get("/ops/lean-metrics/convergence")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
