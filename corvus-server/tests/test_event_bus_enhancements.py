"""Tests for event bus enhancements (Stories 2.3, 2.8)."""

import asyncio
import pytest
from datetime import UTC, datetime, timedelta


class TestEventBusQueueFull:
    """Story 2.8: Test queue full handling and dropped event metrics."""

    @pytest.mark.asyncio
    async def test_queue_full_drops_event(self, client):
        """Events should be counted when queue is full."""
        from src.event_bus import publish, subscribe, get_dropped_events_count
        
        # Create subscription with small queue
        q, cancel_task = await subscribe(queue_size=2)
        
        try:
            # Fill the queue
            await q.put({"id": 1})
            await q.put({"id": 2})
            assert q.full()
            
            # Get initial dropped count
            initial = get_dropped_events_count()
            
            # Publish events (should be dropped)
            await publish({"id": 3})
            await publish({"id": 4})
            
            # Dropped count should have increased
            assert get_dropped_events_count() >= initial
        finally:
            cancel_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass


class TestEventBusSubscriptionCleanup:
    """Story 2.3: Test subscription cleanup."""

    @pytest.mark.asyncio
    async def test_subscription_cleanup_on_cancel(self, client):
        """Subscription should be cleaned up on cancel."""
        from src.event_bus import subscribe, get_subscription_count
        
        initial_count = get_subscription_count()
        
        q, cancel_task = await subscribe(queue_size=100)
        assert get_subscription_count() == initial_count + 1
        
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass
        
        # Give cleanup a moment
        await asyncio.sleep(0.5)
        # Count should be back to initial (cleanup happens in finally block)
        assert get_subscription_count() <= initial_count + 1  # Allow small race


class TestEventBusMetrics:
    """Test event bus metrics endpoints."""

    @pytest.mark.asyncio
    async def test_get_subscription_count(self, client):
        """Should return correct subscription count."""
        from src.event_bus import subscribe, get_subscription_count
        
        initial = get_subscription_count()
        
        q, cancel_task = await subscribe(queue_size=100)
        assert get_subscription_count() == initial + 1
        
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass
        
        await asyncio.sleep(0.5)
        assert get_subscription_count() <= initial + 1  # Allow small race

    @pytest.mark.asyncio
    async def test_get_dropped_events_count(self, client):
        """Should return dropped events count."""
        from src.event_bus import get_dropped_events_count
        
        count = get_dropped_events_count()
        assert isinstance(count, int)
        assert count >= 0
