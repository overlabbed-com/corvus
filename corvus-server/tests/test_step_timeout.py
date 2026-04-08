"""Step timeout reaper tests."""

from datetime import UTC, datetime, timedelta

import pytest

from src.database import get_db
from src.tasks.step_timeout import reap_timed_out_steps


@pytest.mark.asyncio
async def test_reap_timed_out_step(client):
    """Steps executing past their timeout are re-queued."""
    # Create plan, approve, execute
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Timeout test",
            "created_by": "cc",
            "steps": [
                {
                    "name": "slow",
                    "sequence": 1,
                    "action_type": "health.check",
                    "targets": ["svc"],
                    "timeout": 60,
                    "max_retries": 1,
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    step_id = create_resp.json()["steps"][0]["id"]
    await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
    )
    await client.post(f"/ops/plans/{plan_id}/execute")
    # Pull to claim (sets to executing)
    await client.post(f"/ops/plans/{plan_id}/steps/ready")

    # Backdate started_at to 10 minutes ago
    db = await get_db()
    try:
        past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await db.execute(
            "UPDATE ops_plan_steps SET started_at = ? WHERE id = ?",
            (past, step_id),
        )
        await db.commit()
    finally:
        await db.close()

    count = await reap_timed_out_steps()
    assert count == 1

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT status, retry_count FROM ops_plan_steps WHERE id = ?",
            (step_id,),
        )
        row = await cursor.fetchone()
        assert row["status"] == "ready"
        assert row["retry_count"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reap_exhausted_retries_blocks_plan(client):
    """Step that times out past max_retries triggers halt behavior."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Exhausted",
            "created_by": "cc",
            "steps": [
                {
                    "name": "stuck",
                    "sequence": 1,
                    "action_type": "health.check",
                    "targets": ["svc"],
                    "timeout": 60,
                    "max_retries": 0,
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    step_id = create_resp.json()["steps"][0]["id"]
    await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
    )
    await client.post(f"/ops/plans/{plan_id}/execute")
    await client.post(f"/ops/plans/{plan_id}/steps/ready")

    db = await get_db()
    try:
        past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await db.execute(
            "UPDATE ops_plan_steps SET started_at = ? WHERE id = ?",
            (past, step_id),
        )
        await db.commit()
    finally:
        await db.close()

    count = await reap_timed_out_steps()
    assert count == 1

    plan_resp = await client.get(f"/ops/plans/{plan_id}")
    assert plan_resp.json()["status"] == "blocked"


@pytest.mark.asyncio
async def test_reap_ignores_non_timed_out(client):
    """Steps within their timeout are not reaped."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "OK",
            "created_by": "cc",
            "steps": [
                {
                    "name": "fast",
                    "sequence": 1,
                    "action_type": "health.check",
                    "targets": ["svc"],
                    "timeout": 3600,
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
    )
    await client.post(f"/ops/plans/{plan_id}/execute")
    await client.post(f"/ops/plans/{plan_id}/steps/ready")

    count = await reap_timed_out_steps()
    assert count == 0


@pytest.mark.asyncio
async def test_reap_emits_event_on_block(client):
    """Blocking a plan due to timeout emits a plan.blocked event."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Event test",
            "created_by": "cc",
            "steps": [
                {
                    "name": "stuck",
                    "sequence": 1,
                    "action_type": "health.check",
                    "targets": ["svc"],
                    "timeout": 60,
                    "max_retries": 0,
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    step_id = create_resp.json()["steps"][0]["id"]
    await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
    )
    await client.post(f"/ops/plans/{plan_id}/execute")
    await client.post(f"/ops/plans/{plan_id}/steps/ready")

    db = await get_db()
    try:
        past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await db.execute(
            "UPDATE ops_plan_steps SET started_at = ? WHERE id = ?",
            (past, step_id),
        )
        await db.commit()
    finally:
        await db.close()

    await reap_timed_out_steps()

    # Verify plan.blocked event was emitted
    events_resp = await client.get("/ops/events", params={"type": "plan.blocked"})
    events = events_resp.json()
    blocked_events = [e for e in events if e["target"] == plan_id]
    assert len(blocked_events) >= 1
    assert "timed out" in blocked_events[0]["data"]["summary"]


@pytest.mark.asyncio
async def test_reap_skip_policy_does_not_block(client):
    """Step with skip failure_policy that times out does not block the plan."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Skip timeout",
            "created_by": "cc",
            "steps": [
                {
                    "name": "optional",
                    "sequence": 1,
                    "action_type": "health.check",
                    "targets": ["svc"],
                    "timeout": 60,
                    "max_retries": 0,
                    "failure_policy": "skip",
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    step_id = create_resp.json()["steps"][0]["id"]
    await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
    )
    await client.post(f"/ops/plans/{plan_id}/execute")
    await client.post(f"/ops/plans/{plan_id}/steps/ready")

    db = await get_db()
    try:
        past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await db.execute(
            "UPDATE ops_plan_steps SET started_at = ? WHERE id = ?",
            (past, step_id),
        )
        await db.commit()
    finally:
        await db.close()

    count = await reap_timed_out_steps()
    assert count == 1

    # Plan should NOT be blocked — skip policy
    plan_resp = await client.get(f"/ops/plans/{plan_id}")
    # With skip and no downstream steps, plan completes
    assert plan_resp.json()["status"] in ("executing", "completed")
