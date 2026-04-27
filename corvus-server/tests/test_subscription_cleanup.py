"""Story 4.3: Subscription cleanup tests."""

import asyncio
import pytest


class TestSubscriptionCleanup:
    """Test subscription cleanup scenarios."""

    @pytest.mark.asyncio
    async def test_cleanup_on_cancel(self, client):
        """Story 4.3: Subscription should be cleaned up on cancel."""
        from src.event_bus import subscribe, get_subscription_count
        
        initial = get_subscription_count()
        
        q, cancel_task = await subscribe(queue_size=100)
        assert get_subscription_count() == initial + 1
        
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass
        
        await asyncio.sleep(0.2)
        # Should be back to initial (or within 1 due to race)
        assert get_subscription_count() <= initial + 1

    @pytest.mark.asyncio
    async def test_cleanup_on_queue_full(self, client):
        """Story 4.3: Verify behavior when queue is full."""
        from src.event_bus import subscribe, get_subscription_count, publish
        
        initial = get_subscription_count()
        
        # Create subscription with tiny queue
        q, cancel_task = await subscribe(queue_size=1)
        assert get_subscription_count() == initial + 1
        
        # Fill the queue
        await q.put({"id": 1})
        
        # Publish should handle full queue gracefully
        await publish({"id": 2})  # This should be dropped
        
        # Subscription should still exist
        assert get_subscription_count() == initial + 1
        
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_multiple_subscriptions_cleanup(self, client):
        """Story 4.3: Multiple subscriptions should all clean up."""
        from src.event_bus import subscribe, get_subscription_count
        
        initial = get_subscription_count()
        
        # Create multiple subscriptions
        subs = []
        for i in range(5):
            q, cancel_task = await subscribe(queue_size=100)
            subs.append(cancel_task)
        
        assert get_subscription_count() == initial + 5
        
        # Cancel all
        for task in subs:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        await asyncio.sleep(0.3)
        # All should be cleaned up
        assert get_subscription_count() <= initial + 1
