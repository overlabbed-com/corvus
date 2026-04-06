"""Tests for AuthMiddleware — enforces auth on all protected paths.

Tests both the happy path (valid token) and rejection paths (no token,
invalid token, wrong role).
"""

import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient

# Set up isolated test environment before importing app
_test_dir = tempfile.mkdtemp()
os.environ["CORVUS_DATA_DIR"] = _test_dir


@pytest.fixture
def _configure_api_keys(monkeypatch):
    """Configure API keys so auth middleware is active (not dev mode)."""
    from src import config

    test_keys = {
        "admin-key-123": "admin-user:admin",
        "agent-key-456": "nemoclaw:agent",
        "readonly-key-789": "dashboard:ops-read",
    }
    monkeypatch.setattr(config, "API_KEYS", test_keys)
    monkeypatch.setattr(config, "CORVUS_DEV_MODE", False)
    # Also patch the module-level reference in auth middleware
    from src.middleware import auth
    monkeypatch.setattr(auth, "API_KEYS", test_keys)


@pytest.fixture
async def authed_client(_configure_api_keys):
    """Client with API keys configured (auth enforced)."""
    from src.app import app
    from src.database import init_db

    await init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAuthMiddlewareRejectsUnauthenticated:
    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, authed_client):
        resp = await authed_client.get("/ops/events")
        assert resp.status_code == 401
        assert "authorization" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, authed_client):
        resp = await authed_client.get(
            "/ops/events",
            headers={"Authorization": "Bearer invalid-token-xyz"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_changes(self, authed_client):
        resp = await authed_client.get("/ops/changes")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_incidents(self, authed_client):
        resp = await authed_client.get("/ops/incidents")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_cmdb(self, authed_client):
        resp = await authed_client.get("/ops/cmdb")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_problems(self, authed_client):
        resp = await authed_client.get("/ops/problems")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_trust(self, authed_client):
        resp = await authed_client.get("/ops/trust")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_knowledge(self, authed_client):
        resp = await authed_client.get("/ops/knowledge")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_gaps(self, authed_client):
        resp = await authed_client.get("/ops/gaps")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_metrics(self, authed_client):
        resp = await authed_client.get("/ops/metrics")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_runbooks(self, authed_client):
        resp = await authed_client.get("/ops/runbooks")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_on_health(self, authed_client):
        resp = await authed_client.get("/ops/health")
        assert resp.status_code == 401


class TestAuthMiddlewareAllowsPublic:
    @pytest.mark.asyncio
    async def test_root_no_auth(self, authed_client):
        resp = await authed_client.get("/")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_no_auth(self, authed_client):
        resp = await authed_client.get("/health")
        assert resp.status_code == 200


class TestAuthMiddlewareRoleEnforcement:
    @pytest.mark.asyncio
    async def test_admin_can_post_events(self, authed_client):
        resp = await authed_client.post(
            "/ops/events",
            headers={"Authorization": "Bearer admin-key-123"},
            json={
                "source": "test",
                "type": "change.started",
                "target": "test",
            },
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_readonly_cannot_post_events(self, authed_client):
        resp = await authed_client.post(
            "/ops/events",
            headers={"Authorization": "Bearer readonly-key-789"},
            json={
                "source": "test",
                "type": "change.started",
                "target": "test",
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_readonly_can_get_events(self, authed_client):
        resp = await authed_client.get(
            "/ops/events",
            headers={"Authorization": "Bearer readonly-key-789"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_can_create_change(self, authed_client):
        resp = await authed_client.post(
            "/ops/changes",
            headers={"Authorization": "Bearer agent-key-456"},
            json={
                "targets": ["test"],
                "description": "test change",
                "created_by": "nemoclaw",
            },
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_agent_authenticated_as_recorded(self, authed_client):
        """S1.2: authenticated_as should record the actual API key holder."""
        resp = await authed_client.post(
            "/ops/events",
            headers={"Authorization": "Bearer agent-key-456"},
            json={
                "source": "claimed-source",
                "type": "change.started",
                "target": "test",
            },
        )
        assert resp.status_code == 201
        # The source can be anything the caller claims, but authenticated_as
        # should reflect the actual key holder
        data = resp.json()
        assert data.get("authenticated_as") == "nemoclaw"
