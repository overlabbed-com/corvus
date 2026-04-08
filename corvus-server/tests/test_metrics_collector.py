"""Metrics collector tests."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.database import get_db
from src.tasks.metrics_collector import (
    collect_efficiency_metrics,
    collect_throughput_metrics,
    collect_value_stream_metrics,
    store_snapshot,
)


@pytest.mark.asyncio
async def test_incident_cycle_time(client):
    """Incident cycle time computed from resolved incidents."""
    db = await get_db()
    try:
        now = datetime.now(UTC)
        created = (now - timedelta(minutes=30)).isoformat()
        resolved = now.isoformat()
        await db.execute(
            "INSERT INTO ops_incidents (id, created_at, target, title, status, severity, "
            "detected_by, resolved_at, resolution_time_minutes) "
            "VALUES (?, ?, 'svc', 'test', 'resolved', 'medium', 'test', ?, 30)",
            ("INC-TEST01", created, resolved),
        )
        await db.commit()
    finally:
        await db.close()

    metrics = await collect_value_stream_metrics(lookback_hours=1)
    assert "incident_cycle_time" in metrics
    assert metrics["incident_cycle_time"]["count"] >= 1
    # ~1800 seconds (30 min) with some tolerance
    assert metrics["incident_cycle_time"]["p50"] > 1000


@pytest.mark.asyncio
async def test_plan_lead_time(client):
    """Plan lead time computed from completed plans."""
    resp = await client.post(
        "/ops/plans",
        json={
            "title": "Metric test",
            "created_by": "cc",
            "steps": [
                {"name": "s1", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = resp.json()["id"]
    step_id = resp.json()["steps"][0]["id"]
    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "todd", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")
    await client.post(f"/ops/plans/{plan_id}/steps/ready")
    await client.post(f"/ops/plans/{plan_id}/steps/{step_id}/result", json={"success": True})

    metrics = await collect_value_stream_metrics(lookback_hours=1)
    assert "plan_lead_time" in metrics
    assert metrics["plan_lead_time"]["count"] >= 1


@pytest.mark.asyncio
async def test_empty_window_returns_zero_counts(client):
    """No data in window returns metrics with count=0."""
    metrics = await collect_value_stream_metrics(lookback_hours=0)
    for key in ["incident_cycle_time", "plan_lead_time"]:
        if key in metrics:
            assert metrics[key]["count"] == 0


@pytest.mark.asyncio
async def test_throughput_metrics_include_wip(client):
    """Throughput metrics include WIP (active incidents + changes + plans)."""
    metrics = await collect_throughput_metrics(lookback_hours=24)
    assert "wip" in metrics
    assert isinstance(metrics["wip"], int)


@pytest.mark.asyncio
async def test_efficiency_metrics_include_timeout_rate(client):
    """Efficiency metrics include plan step timeout rate."""
    metrics = await collect_efficiency_metrics(lookback_hours=24)
    assert "timeout_rate" in metrics


@pytest.mark.asyncio
async def test_store_snapshot_persists(client):
    """Snapshots are stored in ops_metrics_snapshots."""
    metrics = {"test_metric": {"p50": 10, "count": 1}}
    await store_snapshot("value_stream", metrics)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ops_metrics_snapshots WHERE tier = 'value_stream' "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        assert row is not None
        data = json.loads(row["metrics"])
        assert data["test_metric"]["p50"] == 10
    finally:
        await db.close()
