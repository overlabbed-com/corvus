"""Story 4.2: Multi-adapter failure scenarios."""

from unittest.mock import AsyncMock, patch

import pytest


class TestMultiAdapterFailure:
    """Test SIEM multi-adapter failure handling."""

    @pytest.mark.asyncio
    async def test_partial_failure_continues(self):
        """Story 4.2: If one adapter fails, others should continue."""
        from src.siem import forwarder as fwd_module
        from src.siem.forwarder import forward_to_siem

        # Reset adapters
        fwd_module._adapters = None

        # Mock two adapters: one fails, one succeeds
        mock_adapter1 = AsyncMock()
        mock_adapter1.name = "splunk"
        mock_adapter1.forward = AsyncMock(return_value=False)
        mock_adapter1.max_retries = 0

        mock_adapter2 = AsyncMock()
        mock_adapter2.name = "sentinel"
        mock_adapter2.forward = AsyncMock(return_value=True)
        mock_adapter2.max_retries = 0

        # Patch the _get_adapters function
        with patch.object(fwd_module, "_get_adapters", return_value=[mock_adapter1, mock_adapter2]):
            result = await forward_to_siem({"test": "event"})

            # Should return True because at least one succeeded
            assert result is True
            # Both adapters should be called at least once
            assert mock_adapter1.forward.call_count >= 1
            assert mock_adapter2.forward.call_count >= 1

    @pytest.mark.asyncio
    async def test_all_failures_returns_false(self):
        """Story 4.2: If all adapters fail, returns False."""
        from src.siem import forwarder as fwd_module
        from src.siem.forwarder import forward_to_siem

        fwd_module._adapters = None

        mock_adapter = AsyncMock()
        mock_adapter.name = "splunk"
        mock_adapter.forward = AsyncMock(return_value=False)
        mock_adapter.max_retries = 0

        with patch.object(fwd_module, "_get_adapters", return_value=[mock_adapter]):
            result = await forward_to_siem({"test": "event"})

            # Should return False
            assert result is False
            # Should be called for each retry attempt (3 attempts with 0 retries = 1 call)
            assert mock_adapter.forward.call_count >= 1
