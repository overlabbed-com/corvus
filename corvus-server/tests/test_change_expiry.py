"""Tests for change window auto-expiry."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.database import get_db
from src.tasks.change_expiry import expire_stale_changes


@pytest.mark.asyncio
async def test_expire_stale_changes(client):
    """Expired change windows should be transitioned to 'expired'."""
    # Create a change that's already expired
    db = await get_db()
    try:
        past = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        await db.execute(
            """INSERT INTO ops_changes
               (id, created_at, created_by, status, targets, description,
                auto_expire, expires_at)
               VALUES (?, ?, 'test', 'active', ?, 'Test change', 1, ?)""",
            ("CHG-EXPIRED1", past, json.dumps(["svc-a"]), past),
        )
        await db.commit()
    finally:
        await db.close()

    # Run expiry
    count = await expire_stale_changes()
    assert count == 1

    # Verify it was expired
    resp = await client.get("/ops/changes", params={"status": "expired"})
    changes = resp.json()
    expired_ids = [c["id"] for c in changes]
    assert "CHG-EXPIRED1" in expired_ids


@pytest.mark.asyncio
async def test_active_changes_not_expired(client):
    """Non-expired active changes should remain active."""
    # Create a change with future expiry
    resp = await client.post(
        "/ops/changes",
        json={
            "targets": ["svc-future"],
            "description": "Not expired yet",
            "created_by": "test",
        },
    )
    change_id = resp.json()["id"]

    await expire_stale_changes()
    # Should not expire the future change
    resp = await client.get("/ops/changes", params={"status": "active"})
    active_ids = [c["id"] for c in resp.json()]
    assert change_id in active_ids
