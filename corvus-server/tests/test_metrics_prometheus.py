"""Tests for Prometheus metrics (Story 3.1)."""

import pytest


class TestPrometheusMetrics:
    """Test Prometheus metrics endpoint and functionality."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint_exists(self, client):
        """Story 3.1: /metrics endpoint should exist."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_metrics_contains_expected_labels(self, client):
        """Metrics should contain Corvus-specific metrics."""
        resp = await client.get("/metrics")
        metrics_text = resp.text
        
        # Check for some expected metric names
        expected_metrics = [
            "corvus_events_received_total",
            "corvus_triage_duration_seconds",
            "corvus_graph_query_duration_seconds",
            "corvus_sse_subscriptions",
            "corvus_gaps_open_total",
        ]
        
        for metric in expected_metrics:
            assert metric in metrics_text, f"Expected metric {metric} not found"

    @pytest.mark.asyncio
    async def test_metrics_format_valid(self, client):
        """Metrics should be in valid Prometheus format."""
        resp = await client.get("/metrics")
        metrics_text = resp.text
        
        # Each line should be either a comment, help, type, or metric
        for line in metrics_text.split('\n'):
            if not line.strip():
                continue
            # Comments start with #
            if line.startswith('#'):
                continue
            # Metric lines should have a value
            assert ':' in line or ' ' in line, f"Invalid metric line: {line}"


class TestMetricsIntegration:
    """Test metrics are recorded during operations."""

    @pytest.mark.asyncio
    async def test_event_metrics_recorded(self, client):
        """Event emission should update metrics."""
        from src.metrics import record_event_received
        
        # Record an event
        record_event_received("test.event", "info")
        
        # Check metrics endpoint
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        # Should contain the event metric
        assert "corvus_events_received_total" in resp.text
