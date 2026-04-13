"""Tests for pattern quality API."""

import pytest


@pytest.mark.asyncio
async def test_list_patterns_empty(client):
    """Test listing patterns when none exist."""
    resp = await client.get("/ops/patterns")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_pattern_not_found(client):
    """Test getting non-existent pattern."""
    resp = await client.get("/ops/patterns/non-existent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_bottom_patterns_empty(client):
    """Test bottom patterns when none exist."""
    resp = await client.get("/ops/patterns/bottom-10")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_top_patterns_empty(client):
    """Test top patterns when none exist."""
    resp = await client.get("/ops/patterns/top-10")
    assert resp.status_code == 200
    assert resp.json() == []
