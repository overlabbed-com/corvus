"""Tests for enhanced health checks (Story 3.2)."""

import pytest


class TestHealthReadiness:
    """Test /health/ready endpoint."""

    @pytest.mark.asyncio
    async def test_readiness_endpoint_exists(self, client):
        """Story 3.2: /health/ready endpoint should exist."""
        resp = await client.get("/health/ready")
        assert resp.status_code in [200, 503]  # Ready or not ready
        assert "status" in resp.json()
        assert "checks" in resp.json()

    @pytest.mark.asyncio
    async def test_readiness_checks_database(self, client):
        """Readiness should check database health."""
        resp = await client.get("/health/ready")
        checks = resp.json()["checks"]
        
        assert "database" in checks
        assert "healthy" in checks["database"]
        assert "graph" in checks


class TestHealthDetailed:
    """Test /health/detailed endpoint."""

    @pytest.mark.asyncio
    async def test_detailed_endpoint_exists(self, client):
        """Story 3.2: /health/detailed endpoint should exist."""
        resp = await client.get("/health/detailed")
        assert resp.status_code == 200
        data = resp.json()
        
        assert "status" in data
        assert "database" in data
        assert "graph" in data
        assert "subscriptions" in data
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_detailed_includes_subscription_metrics(self, client):
        """Detailed health should include subscription info."""
        resp = await client.get("/health/detailed")
        data = resp.json()
        
        assert "active_count" in data["subscriptions"]
        assert "dropped_events" in data["subscriptions"]

    @pytest.mark.asyncio
    async def test_detailed_includes_siem_stats(self, client):
        """Detailed health should include SIEM forwarding stats."""
        resp = await client.get("/health/detailed")
        data = resp.json()
        
        assert "siem" in data
        assert "siem_configured" in data["siem"]
