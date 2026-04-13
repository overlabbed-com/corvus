"""Tests for correlation group functionality."""


import pytest


@pytest.mark.asyncio
async def test_check_correlation_single_incident(client):
    """Need at least 2 incidents to check correlation."""
    resp = await client.post(
        "/ops/correlations/check",
        json={"incidents": ["INC-001"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlated"] is False
    assert "Need at least 2 incidents" in data["message"]


@pytest.mark.asyncio
async def test_check_correlation_no_shared_resource(client, requires_neo4j):
    """Independent incidents should not be correlated."""
    # Create 2 independent incidents
    resp = await client.post(
        "/ops/incidents",
        json={
            "title": "Service A failed",
            "severity": "warning",
            "target": "service-a",
            "source": "test",
        },
    )
    incident1_id = resp.json()["id"]

    resp = await client.post(
        "/ops/incidents",
        json={
            "title": "Service B failed",
            "severity": "warning",
            "target": "service-b",
            "source": "test",
        },
    )
    incident2_id = resp.json()["id"]

    resp = await client.post(
        "/ops/correlations/check",
        json={"incidents": [incident1_id, incident2_id]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlated"] is False
    assert "No shared resources detected" in data["message"]


@pytest.mark.asyncio
async def test_check_correlation_shared_gpu(client, requires_neo4j):
    """2 incidents on same GPU should be correlated."""
    # Create 2 incidents affecting services on the same GPU
    resp = await client.post(
        "/ops/incidents",
        json={
            "title": "Service ace-step OOM",
            "severity": "critical",
            "target": "ace-step",
            "source": "test",
        },
    )
    incident1_id = resp.json()["id"]

    resp = await client.post(
        "/ops/incidents",
        json={
            "title": "Service docling failed",
            "severity": "warning",
            "target": "docling",
            "source": "test",
        },
    )
    incident2_id = resp.json()["id"]

    resp = await client.post(
        "/ops/correlations/check",
        json={"incidents": [incident1_id, incident2_id]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlated"] is True
    assert data["group"]["shared_resource_type"] == "gpu"
    assert "gpu:host-03:0" in data["group"]["shared_resource"]
    assert len(data["group"]["member_incidents"]) == 2


@pytest.mark.asyncio
async def test_check_correlation_shared_dependency(client, requires_neo4j):
    """2 incidents with shared unhealthy dependency should be correlated."""
    # Create 2 incidents affecting services that depend on the same unhealthy service
    resp = await client.post(
        "/ops/incidents",
        json={
            "title": "Service sonarr failed",
            "severity": "warning",
            "target": "sonarr",
            "source": "test",
        },
    )
    incident1_id = resp.json()["id"]

    resp = await client.post(
        "/ops/incidents",
        json={
            "title": "Service radarr failed",
            "severity": "warning",
            "target": "radarr",
            "source": "test",
        },
    )
    incident2_id = resp.json()["id"]

    resp = await client.post(
        "/ops/correlations/check",
        json={"incidents": [incident1_id, incident2_id]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlated"] is True
    assert data["group"]["shared_resource_type"] == "dependency"
    assert "dependency:prowlarr" in data["group"]["shared_resource"]
    assert "Fix dependency" in data["group"]["root_cause"]


@pytest.mark.asyncio
async def test_get_correlation_group(client, requires_neo4j):
    """Get correlation group details."""
    # The setup should have created a correlation group
    resp = await client.get("/ops/correlations/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0

    group_id = data["groups"][0]["group_id"]

    resp = await client.get(f"/ops/correlations/group/{group_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["group_id"] == group_id
    assert data["shared_resource_type"] == "gpu"
    assert data["member_count"] >= 2


@pytest.mark.asyncio
async def test_list_active_correlations(client, requires_neo4j):
    """List active correlation groups."""
    resp = await client.get("/ops/correlations/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0

    for group in data["groups"]:
        assert "group_id" in group
        assert "root_cause" in group
        assert "shared_resource" in group
        assert "shared_resource_type" in group
        assert "member_incidents" in group
        assert "member_count" in group
        assert "open_count" in group


@pytest.mark.asyncio
async def test_check_correlation_graph_unavailable(client, neo4j_config):
    """Should handle graph database unavailable gracefully."""
    # If Neo4j is configured, this test doesn't apply
    if neo4j_config["configured"]:
        pytest.skip("Neo4j is configured — test for unconfigured state")

    # When graph is unavailable, should return correlated=False with appropriate message
    resp = await client.post(
        "/ops/correlations/check",
        json={"incidents": ["INC-001", "INC-002"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlated"] is False
    assert "Graph database not available" in data["message"]





@pytest.mark.asyncio
async def test_get_correlation_group_not_found(client, requires_neo4j):
    """Should return 404 for non-existent correlation group."""
    resp = await client.get("/ops/correlations/group/CG-FAKE123")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]
