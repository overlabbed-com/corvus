"""Tests for the agent instructions endpoint."""

import pytest


@pytest.mark.asyncio
async def test_agent_instructions_returns_markdown(client):
    """GET /agent-instructions returns markdown text."""
    resp = await client.get("/agent-instructions")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert "# Corvus" in text
    assert "## Core Concepts" in text
    assert "## Workflows" in text


@pytest.mark.asyncio
async def test_agent_instructions_includes_endpoints(client):
    """Instructions include API endpoint documentation."""
    resp = await client.get("/agent-instructions")
    text = resp.text
    # Should document key endpoints
    assert "/ops/changes" in text
    assert "/ops/incidents" in text
    assert "/ops/events" in text
    assert "/ops/cmdb" in text


@pytest.mark.asyncio
async def test_agent_instructions_includes_workflows(client):
    """Instructions include operational workflows."""
    resp = await client.get("/agent-instructions")
    text = resp.text
    assert "Before Modifying Infrastructure" in text
    assert "Investigating an Incident" in text
    assert "Session Start" in text
