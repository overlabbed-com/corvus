"""Tests for web dashboard."""


class TestDashboardPages:
    async def test_overview_page(self, client):
        resp = await client.get("/dashboard")
        assert resp.status_code == 200
        assert "Fleet Overview" in resp.text
        assert "htmx" in resp.text

    async def test_incidents_page(self, client):
        resp = await client.get("/dashboard/incidents")
        assert resp.status_code == 200
        assert "Incidents" in resp.text

    async def test_changes_page(self, client):
        resp = await client.get("/dashboard/changes")
        assert resp.status_code == 200
        assert "Change Windows" in resp.text

    async def test_services_page(self, client):
        resp = await client.get("/dashboard/services")
        assert resp.status_code == 200
        assert "CMDB Services" in resp.text

    async def test_events_page(self, client):
        resp = await client.get("/dashboard/events")
        assert resp.status_code == 200
        assert "Event Stream" in resp.text

    async def test_knowledge_page(self, client):
        resp = await client.get("/dashboard/knowledge")
        assert resp.status_code == 200
        assert "Knowledge Base" in resp.text


class TestDashboardFragments:
    async def test_stats_fragment(self, client):
        resp = await client.get("/dashboard/fragment/stats")
        assert resp.status_code == 200
        assert "stat-card" in resp.text

    async def test_incidents_fragment(self, client):
        resp = await client.get("/dashboard/fragment/incidents")
        assert resp.status_code == 200
        assert "<table>" in resp.text

    async def test_events_fragment(self, client):
        resp = await client.get("/dashboard/fragment/events")
        assert resp.status_code == 200
        assert "<table>" in resp.text

    async def test_events_full_fragment(self, client):
        resp = await client.get("/dashboard/fragment/events-full")
        assert resp.status_code == 200

    async def test_knowledge_search_empty(self, client):
        resp = await client.get("/dashboard/fragment/knowledge-search?q=")
        assert resp.status_code == 200
        assert "Enter a search query" in resp.text


class TestDashboardWithData:
    async def test_overview_shows_incident_count(self, client):
        # Create an incident
        await client.post(
            "/ops/incidents",
            json={
                "target": "test-svc",
                "title": "Test incident",
                "severity": "warning",
                "detected_by": "test",
            },
        )

        resp = await client.get("/dashboard")
        assert resp.status_code == 200
        # Should show at least 1 open incident
        assert "1" in resp.text

    async def test_services_page_shows_cmdb(self, client):
        # Register a service
        await client.post(
            "/ops/cmdb/register",
            json={
                "name": "dashboard-test-svc",
                "host": "test-host",
                "service_type": "test",
                "critical": True,
                "registered_by": "test",
            },
        )

        resp = await client.get("/dashboard/services")
        assert resp.status_code == 200
        assert "dashboard-test-svc" in resp.text

    async def test_knowledge_search_returns_results(self, client):
        # Add knowledge
        await client.post(
            "/ops/knowledge",
            json={
                "title": "Docker bridge NAT fix",
                "content": "Use ipvlan with explicit default route via gateway",
            },
        )

        resp = await client.get("/dashboard/fragment/knowledge-search?q=Docker bridge NAT")
        assert resp.status_code == 200
        assert "ipvlan" in resp.text
