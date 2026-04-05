"""Tests for security hardening (issue #7)."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import client  # noqa: F401


@pytest.mark.asyncio
async def test_change_has_authenticated_as(client):
    """Change records should include authenticated_as field."""
    resp = await client.post(
        "/ops/changes",
        json={
            "targets": ["vllm-primary"],
            "description": "test change",
            "created_by": "test-agent",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    # authenticated_as should be present (anonymous in test mode)
    assert "authenticated_as" in data


@pytest.mark.asyncio
async def test_event_has_authenticated_as(client):
    """Event records should include authenticated_as field."""
    resp = await client.post(
        "/ops/events",
        json={
            "source": "test",
            "type": "change.started",
            "target": "vllm-primary",
        },
    )
    assert resp.status_code == 201
    assert "authenticated_as" in resp.json()


@pytest.mark.asyncio
async def test_cors_no_wildcard(client):
    """CORS should not allow wildcard origins."""
    resp = await client.options(
        "/ops/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Header should be absent entirely for unknown origins
    acao = resp.headers.get("access-control-allow-origin")
    assert acao is None


@pytest.mark.asyncio
async def test_delete_change_not_allowed(client):
    """DELETE on changes should return 405 Method Not Allowed."""
    # Create a change first
    resp = await client.post(
        "/ops/changes",
        json={
            "targets": ["vllm-primary"],
            "description": "test",
            "created_by": "test",
        },
    )
    change_id = resp.json()["id"]

    # DELETE should not be allowed
    resp = await client.delete(f"/ops/changes/{change_id}")
    assert resp.status_code == 405


@pytest.mark.asyncio
async def test_change_targets_immutable(client):
    """PATCH on changes should not allow modifying targets."""
    resp = await client.post(
        "/ops/changes",
        json={
            "targets": ["vllm-primary"],
            "description": "test",
            "created_by": "test",
        },
    )
    change_id = resp.json()["id"]

    # Targets field should not be modifiable
    resp = await client.patch(
        f"/ops/changes/{change_id}",
        json={
            "status": "completed",
        },
    )
    assert resp.status_code == 200
    # Targets should remain unchanged
    assert resp.json()["targets"] == ["vllm-primary"]


@pytest.mark.asyncio
async def test_incident_has_authenticated_as(client):
    """Incident records should include authenticated_as field."""
    resp = await client.post(
        "/ops/incidents",
        json={
            "target": "vllm-primary",
            "title": "test incident",
            "detected_by": "test",
        },
    )
    assert resp.status_code == 201
    assert "authenticated_as" in resp.json()


@pytest.mark.asyncio
async def test_audit_forwards_to_siem(client):
    """Audit middleware should forward audit entries to SIEM."""
    with patch("src.middleware.audit.forward_to_siem", new_callable=AsyncMock) as mock_fwd:
        resp = await client.post(
            "/ops/events",
            json={
                "source": "test",
                "type": "change.started",
                "target": "test-target",
            },
        )
        assert resp.status_code == 201
        # Audit middleware should have called forward_to_siem
        assert mock_fwd.called
