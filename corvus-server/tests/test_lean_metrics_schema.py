"""Lean metrics schema tests --- verify tables and columns exist."""

import pytest

from src.database import get_db


@pytest.mark.asyncio
async def test_metrics_snapshots_table_exists(client):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ops_metrics_snapshots'")
        assert await cursor.fetchone() is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_metric_adjustments_table_exists(client):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ops_metric_adjustments'")
        assert await cursor.fetchone() is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_incidents_has_investigating_at(client):
    db = await get_db()
    try:
        cursor = await db.execute("PRAGMA table_info(ops_incidents)")
        columns = [row["name"] for row in await cursor.fetchall()]
        assert "investigating_at" in columns
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_trust_ledger_has_first_seen_at(client):
    db = await get_db()
    try:
        cursor = await db.execute("PRAGMA table_info(ops_trust_ledger)")
        columns = [row["name"] for row in await cursor.fetchall()]
        assert "first_seen_at" in columns
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_triage_log_has_resolution_time_seconds(client):
    db = await get_db()
    try:
        cursor = await db.execute("PRAGMA table_info(ops_triage_log)")
        columns = [row["name"] for row in await cursor.fetchall()]
        assert "resolution_time_seconds" in columns
    finally:
        await db.close()
