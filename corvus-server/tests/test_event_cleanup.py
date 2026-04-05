"""Tests for event cleanup and retention policy."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.database import get_db
from src.tasks.event_cleanup import (
    get_table_sizes,
    prune_audit_log,
    prune_events,
    prune_triage_log,
)


async def _insert_event(db, event_id: str, timestamp: str):
    """Insert a test event with a specific timestamp."""
    await db.execute(
        """INSERT INTO ops_events (id, timestamp, source, type, target, severity, data)
           VALUES (?, ?, 'test', 'test.event', 'svc-a', 'info', '{}')""",
        (event_id, timestamp),
    )


async def _insert_audit(db, timestamp: str):
    """Insert a test audit log entry."""
    await db.execute(
        """INSERT INTO ops_audit_log (timestamp, actor, action, resource)
           VALUES (?, 'test', 'GET', '/test')""",
        (timestamp,),
    )


async def _insert_triage(db, triage_id: str, timestamp: str):
    """Insert a test triage log entry."""
    await db.execute(
        """INSERT INTO ops_triage_log
           (id, timestamp, target, service_type, runbook_name, action_type)
           VALUES (?, ?, 'svc-a', 'inference', 'test-runbook', 'restart')""",
        (triage_id, timestamp),
    )


@pytest.mark.asyncio
async def test_prune_events_removes_old(client):
    """Events older than retention are deleted."""
    db = await get_db()
    try:
        now = datetime.now(UTC)
        old_ts = (now - timedelta(days=100)).isoformat()
        new_ts = (now - timedelta(days=10)).isoformat()

        await _insert_event(db, "EVT-OLD", old_ts)
        await _insert_event(db, "EVT-NEW", new_ts)
        await db.commit()
    finally:
        await db.close()

    with patch("src.tasks.event_cleanup.ARCHIVE_BEFORE_DELETE", False):
        result = await prune_events()

    assert result["deleted"] >= 1

    # Verify new event still exists
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM ops_events WHERE id = 'EVT-NEW'")
        assert await cursor.fetchone() is not None
        cursor = await db.execute("SELECT id FROM ops_events WHERE id = 'EVT-OLD'")
        assert await cursor.fetchone() is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prune_events_preserves_recent(client):
    """Events within retention window are preserved."""
    db = await get_db()
    try:
        now = datetime.now(UTC)
        recent_ts = (now - timedelta(days=5)).isoformat()
        await _insert_event(db, "EVT-RECENT", recent_ts)
        await db.commit()
    finally:
        await db.close()

    with patch("src.tasks.event_cleanup.ARCHIVE_BEFORE_DELETE", False):
        result = await prune_events()

    assert result["deleted"] == 0

    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM ops_events WHERE id = 'EVT-RECENT'")
        assert await cursor.fetchone() is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prune_events_dry_run(client):
    """Dry run reports count without deleting."""
    db = await get_db()
    try:
        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        await _insert_event(db, "EVT-DRY", old_ts)
        await db.commit()
    finally:
        await db.close()

    result = await prune_events(dry_run=True)
    assert result["would_delete"] >= 1
    assert result["deleted"] == 0

    # Event still exists
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM ops_events WHERE id = 'EVT-DRY'")
        assert await cursor.fetchone() is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prune_audit_log(client):
    """Audit entries older than retention are deleted."""
    db = await get_db()
    try:
        old_ts = (datetime.now(UTC) - timedelta(days=400)).isoformat()
        new_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        await _insert_audit(db, old_ts)
        await _insert_audit(db, new_ts)
        await db.commit()
    finally:
        await db.close()

    result = await prune_audit_log()
    assert result["deleted"] >= 1


@pytest.mark.asyncio
async def test_prune_triage_log(client):
    """Triage entries older than retention are deleted."""
    db = await get_db()
    try:
        old_ts = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        new_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        await _insert_triage(db, "TRI-OLD", old_ts)
        await _insert_triage(db, "TRI-NEW", new_ts)
        await db.commit()
    finally:
        await db.close()

    result = await prune_triage_log()
    assert result["deleted"] >= 1

    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM ops_triage_log WHERE id = 'TRI-NEW'")
        assert await cursor.fetchone() is not None
        cursor = await db.execute("SELECT id FROM ops_triage_log WHERE id = 'TRI-OLD'")
        assert await cursor.fetchone() is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_table_sizes(client):
    """Table sizes returns counts for all tables."""
    sizes = await get_table_sizes()
    assert "ops_events" in sizes
    assert "ops_incidents" in sizes
    assert "ops_audit_log" in sizes
    assert all(isinstance(v, int) for v in sizes.values())


@pytest.mark.asyncio
async def test_cleanup_endpoint(client):
    """POST /ops/cleanup runs cleanup and returns results."""
    resp = await client.post("/ops/cleanup?dry_run=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    assert "events" in data
    assert "audit_log" in data
    assert "triage_log" in data


@pytest.mark.asyncio
async def test_metrics_include_table_sizes(client):
    """Metrics endpoint includes table sizes and retention policy."""
    resp = await client.get("/ops/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "table_sizes" in data
    assert "retention_policy" in data
    assert data["retention_policy"]["events_days"] == 90
