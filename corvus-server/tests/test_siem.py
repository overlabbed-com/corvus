"""Tests for SIEM adapters and forwarder."""

from unittest.mock import AsyncMock, patch

import pytest

from src.siem.chronicle import ChronicleAdapter
from src.siem.elastic import ElasticAdapter
from src.siem.forwarder import (
    _init_adapters,
    forward_to_siem,
    get_dead_letters,
    get_forwarding_stats,
)
from src.siem.sentinel import SentinelAdapter
from src.siem.splunk import SplunkAdapter

# ---------------------------------------------------------------------------
# Adapter configuration tests
# ---------------------------------------------------------------------------


class TestSplunkAdapter:
    def test_configured_with_url_and_token(self):
        adapter = SplunkAdapter(url="https://splunk.example.com", token="abc123")
        assert adapter.is_configured() is True

    def test_not_configured_missing_url(self):
        adapter = SplunkAdapter(url="", token="abc123")
        assert adapter.is_configured() is False

    def test_not_configured_missing_token(self):
        adapter = SplunkAdapter(url="https://splunk.example.com", token="")
        assert adapter.is_configured() is False

    def test_name(self):
        assert SplunkAdapter().name == "splunk"


class TestSentinelAdapter:
    def test_configured_with_workspace_and_key(self):
        adapter = SentinelAdapter(workspace_id="ws-123", shared_key="c2hhcmVk")
        assert adapter.is_configured() is True

    def test_not_configured_missing_workspace(self):
        adapter = SentinelAdapter(workspace_id="", shared_key="c2hhcmVk")
        assert adapter.is_configured() is False

    def test_not_configured_missing_key(self):
        adapter = SentinelAdapter(workspace_id="ws-123", shared_key="")
        assert adapter.is_configured() is False

    def test_name(self):
        assert SentinelAdapter().name == "sentinel"


class TestChronicleAdapter:
    def test_configured_with_api_key_and_customer(self):
        adapter = ChronicleAdapter(api_key="key-123", customer_id="cust-456")
        assert adapter.is_configured() is True

    def test_not_configured_missing_api_key(self):
        adapter = ChronicleAdapter(api_key="", customer_id="cust-456")
        assert adapter.is_configured() is False

    def test_not_configured_missing_customer(self):
        adapter = ChronicleAdapter(api_key="key-123", customer_id="")
        assert adapter.is_configured() is False

    def test_name(self):
        assert ChronicleAdapter().name == "chronicle"


class TestElasticAdapter:
    def test_configured_with_url_and_api_key(self):
        adapter = ElasticAdapter(url="https://es.example.com", api_key="key-123")
        assert adapter.is_configured() is True

    def test_configured_with_url_and_basic_auth(self):
        adapter = ElasticAdapter(url="https://es.example.com", username="admin", password="secret")
        assert adapter.is_configured() is True

    def test_not_configured_missing_url(self):
        adapter = ElasticAdapter(url="", api_key="key-123")
        assert adapter.is_configured() is False

    def test_not_configured_missing_all_auth(self):
        adapter = ElasticAdapter(url="https://es.example.com")
        assert adapter.is_configured() is False

    def test_not_configured_partial_basic_auth(self):
        adapter = ElasticAdapter(url="https://es.example.com", username="admin")
        assert adapter.is_configured() is False

    def test_name(self):
        assert ElasticAdapter().name == "elastic"

    def test_index_name_has_date(self):
        adapter = ElasticAdapter(url="https://es.example.com", api_key="key", index_prefix="test-ocsf")
        index = adapter._index_name()
        assert index.startswith("test-ocsf-")
        # Date format YYYY.MM.DD
        parts = index.split("-", 2)
        assert "." in parts[2]


# ---------------------------------------------------------------------------
# Base adapter stats and dead-letter tests
# ---------------------------------------------------------------------------


class TestAdapterStats:
    def test_initial_stats(self):
        adapter = SplunkAdapter(url="https://splunk.example.com", token="abc")
        stats = adapter.get_stats()
        assert stats["adapter"] == "splunk"
        assert stats["forwarded"] == 0
        assert stats["failed"] == 0
        assert stats["retries"] == 0
        assert stats["dead_letter_count"] == 0
        assert stats["configured"] is True

    def test_empty_dead_letters(self):
        adapter = SplunkAdapter(url="https://splunk.example.com", token="abc")
        assert adapter.get_dead_letters() == []


class TestAdapterForwarding:
    @pytest.mark.asyncio
    async def test_unconfigured_adapter_returns_false(self):
        adapter = SplunkAdapter()  # No credentials
        result = await adapter.forward({"class_uid": 1001})
        assert result is False
        # Should not increment any stats
        assert adapter.get_stats()["forwarded"] == 0
        assert adapter.get_stats()["failed"] == 0

    @pytest.mark.asyncio
    async def test_success_increments_forwarded(self):
        adapter = SplunkAdapter(url="https://splunk.example.com", token="abc")
        adapter._send = AsyncMock(return_value=True)
        result = await adapter.forward({"class_uid": 1001})
        assert result is True
        assert adapter.get_stats()["forwarded"] == 1
        assert adapter.get_stats()["failed"] == 0

    @pytest.mark.asyncio
    async def test_failure_goes_to_dead_letter(self):
        adapter = SplunkAdapter(url="https://splunk.example.com", token="abc")
        adapter.max_retries = 1  # Speed up test
        adapter._send = AsyncMock(return_value=False)
        result = await adapter.forward({"class_uid": 1001})
        assert result is False
        assert adapter.get_stats()["failed"] == 1
        assert adapter.get_stats()["dead_letter_count"] == 1
        dead = adapter.get_dead_letters()
        assert len(dead) == 1
        assert dead[0]["adapter"] == "splunk"
        assert dead[0]["event"]["class_uid"] == 1001

    @pytest.mark.asyncio
    async def test_exception_retries_then_dead_letter(self):
        adapter = SplunkAdapter(url="https://splunk.example.com", token="abc")
        adapter.max_retries = 2
        adapter._send = AsyncMock(side_effect=ConnectionError("timeout"))
        result = await adapter.forward({"class_uid": 1001})
        assert result is False
        assert adapter._send.call_count == 2
        assert adapter.get_stats()["retries"] == 2
        assert adapter.get_stats()["failed"] == 1
        assert adapter.get_stats()["dead_letter_count"] == 1

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        adapter = SplunkAdapter(url="https://splunk.example.com", token="abc")
        adapter.max_retries = 3
        adapter._send = AsyncMock(side_effect=[False, True])
        result = await adapter.forward({"class_uid": 1001})
        assert result is True
        assert adapter.get_stats()["forwarded"] == 1
        assert adapter.get_stats()["retries"] == 1
        assert adapter.get_stats()["failed"] == 0


# ---------------------------------------------------------------------------
# Forwarder module tests
# ---------------------------------------------------------------------------


class TestForwarderModule:
    @pytest.mark.asyncio
    async def test_no_adapters_stats(self):
        """"With no SIEM configured, stats report none."""
        stats = await get_forwarding_stats()
        assert stats["siem_configured"] is False
        assert stats["adapter"] == "none"
        assert stats["forwarded"] == 0

    @patch.dict("os.environ", {"CORVUS_SIEM_TYPE": "unknown_type"})
    def test_unknown_siem_type_skipped(self):
        """Unknown SIEM types are logged and skipped."""
        from src.siem import forwarder

        old = forwarder._adapters
        forwarder._adapters = None  # Force re-init
        try:
            adapters = _init_adapters()
            assert len(adapters) == 0
        finally:
            forwarder._adapters = old

    @patch.dict(
        "os.environ",
        {
            "CORVUS_SIEM_TYPE": "splunk",
            "CORVUS_SIEM_URL": "https://splunk.example.com",
            "CORVUS_SIEM_TOKEN": "test-token",
        },
    )
    def test_splunk_adapter_init_from_env(self):
        """Splunk adapter initializes from env vars."""
        from src.siem import forwarder

        old = forwarder._adapters
        forwarder._adapters = None
        try:
            adapters = _init_adapters()
            assert len(adapters) == 1
            assert adapters[0].name == "splunk"
        finally:
            forwarder._adapters = old

    @patch.dict(
        "os.environ",
        {
            "CORVUS_SIEM_TYPE": "elastic",
            "CORVUS_ELASTIC_URL": "https://es.example.com",
            "CORVUS_ELASTIC_API_KEY": "test-key",
        },
    )
    def test_elastic_adapter_init_from_env(self):
        """Elastic adapter initializes from env vars."""
        from src.siem import forwarder

        old = forwarder._adapters
        forwarder._adapters = None
        try:
            adapters = _init_adapters()
            assert len(adapters) == 1
            assert adapters[0].name == "elastic"
        finally:
            forwarder._adapters = old

    @patch.dict(
        "os.environ",
        {
            "CORVUS_SIEM_TYPE": "splunk,elastic",
            "CORVUS_SIEM_URL": "https://splunk.example.com",
            "CORVUS_SIEM_TOKEN": "test-token",
            "CORVUS_ELASTIC_URL": "https://es.example.com",
            "CORVUS_ELASTIC_API_KEY": "test-key",
        },
    )
    def test_multi_adapter_stats(self):
        """Multiple adapters aggregate stats."""
        from src.siem import forwarder

        old = forwarder._adapters
        forwarder._adapters = None
        try:
            adapters = _init_adapters()
            assert len(adapters) == 2
            names = {a.name for a in adapters}
            assert names == {"splunk", "elastic"}
        finally:
            forwarder._adapters = old

    @pytest.mark.asyncio
    async def test_dead_letters_empty_no_adapters(self):
        """"Dead letters returns empty when no adapters configured."""
        from src.siem import forwarder

        old = forwarder._adapters
        forwarder._adapters = []
        try:
            dead = await get_dead_letters()
            assert dead == []
        finally:
            forwarder._adapters = old

    @pytest.mark.asyncio
    async def test_forward_no_adapters_returns_false(self):
        """Forwarding with no adapters returns False."""
        from src.siem import forwarder

        old = forwarder._adapters
        forwarder._adapters = []
        try:
            result = await forward_to_siem({"class_uid": 1001})
            assert result is False
        finally:
            forwarder._adapters = old
