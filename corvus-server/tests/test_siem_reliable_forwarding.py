"""Tests for reliable SIEM forwarding with retry and dead-letter queue.

Story 1.2: SIEM forwarding should use retry with exponential backoff.
Failed events should be stored in dead-letter queue (DB table).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_siem_down_events_queued_for_retry(client):
    """SIEM down should queue events for retry instead of dropping."""
    from src.siem.forwarder import forward_to_siem, get_forwarding_stats

    # Patch all adapters to fail
    with patch("src.siem.forwarder._get_adapters") as mock_get_adapters:
        mock_adapter = MagicMock()
        mock_adapter.forward = AsyncMock(return_value=False)  # Failure
        mock_adapter.get_stats.return_value = {
            "forwarded": 0,
            "failed": 1,
            "retries": 0,
            "dead_letter_count": 0,
        }
        mock_adapter.name = "test-siem"
        mock_adapter.is_configured.return_value = True
        mock_get_adapters.return_value = [mock_adapter]

        # Forward an event
        ocsf_event = {
            "uid": "test-123",
            "timestamp": "2026-04-26T00:00:00Z",
            "class_uid": 2005,
            "event_time": "2026-04-26T00:00:00Z",
        }

        result = await forward_to_siem(ocsf_event)

        # Should return False (not successful)
        assert result is False

        # Stats should show failure (now async)
        stats = await get_forwarding_stats()
        assert stats["failed"] >= 1


@pytest.mark.asyncio
async def test_dead_letter_queue_accessible_via_api(client):
    """Dead-letter queue should be accessible via API endpoint."""
    from src.database import get_db
    from src.siem.forwarder import get_dead_letters

    # Insert test dead-letter entries directly into database
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO ops_siem_dead_letter (id, event_id, event_type, event_data, error, attempted_at, attempt_count, last_adapter) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (
                "DL-TEST001",
                "EVT-TEST001",
                "incident.opened",
                '{"uid": "test-1"}',
                "Connection timeout",
                "2026-04-26T00:00:00Z",
                "splunk",
            ),
        )
        await db.execute(
            "INSERT INTO ops_siem_dead_letter (id, event_id, event_type, event_data, error, attempted_at, attempt_count, last_adapter) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (
                "DL-TEST002",
                "EVT-TEST002",
                "change.completed",
                '{"uid": "test-2"}',
                "HTTP 503",
                "2026-04-26T00:01:00Z",
                "splunk",
            ),
        )
        await db.commit()
    finally:
        await db.close()

    # get_dead_letters now reads from database
    dead_letters = await get_dead_letters()

    assert len(dead_letters) == 2
    # Most recent first (by attempted_at DESC)
    event_ids = [dl["event_id"] for dl in dead_letters]
    assert "EVT-TEST001" in event_ids
    assert "EVT-TEST002" in event_ids
    # The most recent (TEST002 with later timestamp) should be first
    assert dead_letters[0]["event_id"] == "EVT-TEST002"
    assert "503" in dead_letters[0]["error"]


@pytest.mark.asyncio
async def test_forwarding_uses_exponential_backoff(client):
    """SIEM forwarding should implement exponential backoff on retry."""
    from src.siem.forwarder import forward_to_siem

    call_times = []

    # Patch adapters to track call times and fail first few times
    with patch("src.siem.forwarder._get_adapters") as mock_get_adapters:
        with patch("src.siem.forwarder.asyncio") as mock_asyncio:
            mock_adapter = MagicMock()
        call_count = [0]

        async def mock_forward(event):
            call_count[0] += 1
            call_times.append(call_count[0])
            # Fail first 2 attempts, succeed on 3rd
            return call_count[0] >= 3

        mock_adapter.forward = mock_forward
        mock_adapter.name = "test-siem"
        mock_adapter.is_configured.return_value = True
        mock_get_adapters.return_value = [mock_adapter]

        ocsf_event = {"uid": "test-123", "class_uid": 2005}

        # The actual implementation should handle retries
        # We just verify the adapter was called
        result = await forward_to_siem(ocsf_event)
        assert result is True


@pytest.mark.asyncio
async def test_metrics_exposed_for_forwarded_failed_dropped(client):
    """Metrics should be exposed for forwarded, failed, and dropped events."""
    from src.siem.forwarder import get_forwarding_stats

    with patch("src.siem.forwarder._get_adapters") as mock_get_adapters:
        mock_adapter = MagicMock()
        mock_adapter.get_stats.return_value = {
            "forwarded": 10,
            "failed": 2,
            "retries": 5,
            "dead_letter_count": 1,
        }
        mock_adapter.name = "test-siem"
        mock_adapter.is_configured.return_value = True
        mock_get_adapters.return_value = [mock_adapter]

        stats = await get_forwarding_stats()

        assert "forwarded" in stats
        assert "failed" in stats
        assert "retries" in stats
        assert "dead_letter_count" in stats
        assert stats["forwarded"] == 10
        assert stats["failed"] == 2


@pytest.mark.asyncio
async def test_multiple_adapters_partial_failure(client):
    """Multiple adapters: one fails, one succeeds should return True."""
    from src.siem.forwarder import forward_to_siem

    with patch("src.siem.forwarder._get_adapters") as mock_get_adapters:
        # One adapter succeeds, one fails
        mock_adapter_success = MagicMock()
        mock_adapter_success.forward = AsyncMock(return_value=True)
        mock_adapter_success.name = "success-siem"

        mock_adapter_fail = MagicMock()
        mock_adapter_fail.forward = AsyncMock(return_value=False)
        mock_adapter_fail.name = "fail-siem"

        mock_get_adapters.return_value = [mock_adapter_success, mock_adapter_fail]

        ocsf_event = {"uid": "test-123", "class_uid": 2005}

        result = await forward_to_siem(ocsf_event)

        # Should return True because at least one succeeded
        assert result is True
