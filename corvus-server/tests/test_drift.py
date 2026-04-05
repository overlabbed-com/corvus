"""Tests for config drift detection.

Verifies that the populator correctly detects drift between declared
(compose) and inspected (runtime) state, covering image and healthcheck
fields. Uses mocked Neo4j sessions since graph DB is not available in CI.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.discovery.declared import DiscoveryResult
from src.discovery.populator import populate_graph


def _make_declared(services: list[dict]) -> DiscoveryResult:
    """Build a minimal DiscoveryResult for declared state."""
    return DiscoveryResult(
        services=services,
        edges=[],
        hosts=[{"name": "testhost", "ip": "10.0.0.1", "role": "test"}],
        gpus=[],
        networks=[],
    )


def _make_inspected(services: list[dict]) -> DiscoveryResult:
    """Build a minimal DiscoveryResult for inspected state."""
    return DiscoveryResult(
        services=services,
        edges=[],
        hosts=[],
        gpus=[],
        networks=[],
    )


def _mock_graph_session():
    """Create a mock graph session context manager."""
    mock_session = AsyncMock()
    mock_session.run = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_ctx():
        yield mock_session

    return mock_ctx, mock_session


class TestDriftDetection:
    """Test drift detection in the populator."""

    @pytest.mark.asyncio
    async def test_no_drift_when_matching(self):
        """No drift when declared and runtime images match."""
        mock_ctx, _ = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "healthcheck": True,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                }
            ]
        )
        inspected = _make_inspected(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "health": "healthy",
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                }
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            stats = await populate_graph(declared, inspected)
        assert stats["drift_count"] == 0

    @pytest.mark.asyncio
    async def test_image_drift_detected(self):
        """Drift detected when declared and runtime images differ."""
        mock_ctx, _ = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.26",
                    "healthcheck": False,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                }
            ]
        )
        inspected = _make_inspected(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "health": "",
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                }
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            stats = await populate_graph(declared, inspected)
        assert stats["drift_count"] == 1

    @pytest.mark.asyncio
    async def test_healthcheck_drift_detected(self):
        """Drift detected when compose has healthcheck but runtime doesn't.

        This is the certbot scenario: compose defines a healthcheck,
        but the container was created before it was added.
        """
        mock_ctx, _ = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "certbot",
                    "host": "testhost",
                    "image": "certbot:latest",
                    "healthcheck": True,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                }
            ]
        )
        inspected = _make_inspected(
            [
                {
                    "name": "certbot",
                    "host": "testhost",
                    "image": "certbot:latest",
                    "health": "",  # No health status = no healthcheck
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                }
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            stats = await populate_graph(declared, inspected)
        assert stats["drift_count"] == 1

    @pytest.mark.asyncio
    async def test_no_healthcheck_drift_when_both_absent(self):
        """No drift when neither compose nor runtime has healthcheck."""
        mock_ctx, _ = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "healthcheck": False,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                }
            ]
        )
        inspected = _make_inspected(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "health": "",
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                }
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            stats = await populate_graph(declared, inspected)
        assert stats["drift_count"] == 0

    @pytest.mark.asyncio
    async def test_multiple_drift_types_same_service(self):
        """Both image and healthcheck drift on same service counts as 1."""
        mock_ctx, _ = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.26",
                    "healthcheck": True,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                }
            ]
        )
        inspected = _make_inspected(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "health": "",
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                }
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            stats = await populate_graph(declared, inspected)
        assert stats["drift_count"] == 1

    @pytest.mark.asyncio
    async def test_drift_across_multiple_services(self):
        """Drift count accumulates across multiple services."""
        mock_ctx, _ = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.26",
                    "healthcheck": False,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                },
                {
                    "name": "svc-b",
                    "host": "testhost",
                    "image": "redis:7.2",
                    "healthcheck": True,
                    "service_type": "cache",
                    "stack": "test",
                    "gpu_indexes": [],
                },
            ]
        )
        inspected = _make_inspected(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "health": "",
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                },
                {
                    "name": "svc-b",
                    "host": "testhost",
                    "image": "redis:7.2",
                    "health": "",
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                },
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            stats = await populate_graph(declared, inspected)
        assert stats["drift_count"] == 2

    @pytest.mark.asyncio
    async def test_no_drift_without_inspected_data(self):
        """No drift when inspected layer is not provided."""
        mock_ctx, _ = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.26",
                    "healthcheck": True,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                }
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            stats = await populate_graph(declared, inspected=None)
        assert stats["drift_count"] == 0

    @pytest.mark.asyncio
    async def test_no_drift_for_undiscovered_runtime(self):
        """No drift for services not found in inspected data."""
        mock_ctx, _ = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.26",
                    "healthcheck": True,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                }
            ]
        )
        inspected = _make_inspected(
            [
                {
                    "name": "other-svc",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "health": "healthy",
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                }
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            stats = await populate_graph(declared, inspected)
        assert stats["drift_count"] == 0

    @pytest.mark.asyncio
    async def test_drift_fields_tracked(self):
        """Verify that Cypher SET call receives correct drift_fields."""
        mock_ctx, mock_session = _mock_graph_session()

        declared = _make_declared(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.26",
                    "healthcheck": True,
                    "service_type": "container",
                    "stack": "test",
                    "gpu_indexes": [],
                }
            ]
        )
        inspected = _make_inspected(
            [
                {
                    "name": "svc-a",
                    "host": "testhost",
                    "image": "nginx:1.25",
                    "health": "",
                    "status": "running",
                    "service_type": "container",
                    "stack": "",
                }
            ]
        )

        with patch("src.discovery.populator.graph_session", mock_ctx):
            await populate_graph(declared, inspected)

        # Find the MERGE call for Service that includes drift_fields
        for call in mock_session.run.call_args_list:
            kwargs = call.kwargs if call.kwargs else {}
            if "drift_fields" in kwargs:
                assert "image" in kwargs["drift_fields"]
                assert "healthcheck" in kwargs["drift_fields"]
                assert kwargs["drift_detected"] is True
                assert kwargs["declared_image"] == "nginx:1.26"
                assert kwargs["runtime_image"] == "nginx:1.25"
                assert kwargs["declared_healthcheck"] is True
                assert kwargs["runtime_healthcheck"] is False
                break
        else:
            pytest.fail("No MERGE call with drift_fields found")
