"""Metrics collector tests."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.database import get_db
from src.tasks.metrics_collector import collect_value_stream_metrics


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
