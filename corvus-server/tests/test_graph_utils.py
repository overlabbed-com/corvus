"""Tests for graph utilities."""

import pytest


@pytest.mark.asyncio
async def test_get_upstream_dependencies_no_graph():
    """Test upstream dependencies when graph unavailable."""
    from src.discovery.graph_utils import get_upstream_dependencies

    deps = await get_upstream_dependencies("test-service")
    assert deps == []


@pytest.mark.asyncio
async def test_get_downstream_dependents_no_graph():
    """Test downstream dependents when graph unavailable."""
    from src.discovery.graph_utils import get_downstream_dependents

    deps = await get_downstream_dependents("test-service")
    assert deps == []


@pytest.mark.asyncio
async def test_find_shared_resources_no_graph():
    """Test shared resources when graph unavailable."""
    from src.discovery.graph_utils import find_shared_resources

    resources = await find_shared_resources(["service1", "service2"])
    assert resources == []


@pytest.mark.asyncio
async def test_check_graph_health_no_graph():
    """Test health check when graph unavailable."""
    from src.discovery.graph_utils import check_graph_health

    health = await check_graph_health(["service1", "service2"])
    assert health == {"service1": "unknown", "service2": "unknown"}


@pytest.mark.asyncio
async def test_root_cause_hypothesis_no_graph():
    """Test root cause hypothesis when graph unavailable."""
    from src.discovery.graph_utils import get_root_cause_hypothesis

    hypothesis = await get_root_cause_hypothesis("test-service", {})
    assert "Unable to analyze" in hypothesis["hypothesis"]
    assert hypothesis["confidence"] == 0.0
