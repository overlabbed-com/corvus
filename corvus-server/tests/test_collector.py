"""Tests for Layer 2: Corvus-native Docker API collector."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import MCP_INTERNAL_KEY
from src.discovery.collector import (
    _hex_to_ip,
    _hex_to_port,
    parse_proc_net_tcp,
)

AUTH = {"Authorization": f"Bearer {MCP_INTERNAL_KEY}"}


# ---------------------------------------------------------------------------
# Hex conversion tests
# ---------------------------------------------------------------------------


class TestHexConversions:
    def test_hex_to_ip_localhost(self):
        # 127.0.0.1 in little-endian hex = 0100007F
        assert _hex_to_ip("0100007F") == "127.0.0.1"

    def test_hex_to_ip_docker_network(self):
        # 172.18.0.15 = AC.12.00.0F → little-endian = 0F0012AC
        assert _hex_to_ip("0F0012AC") == "172.18.0.15"

    def test_hex_to_ip_private_network(self):
        # 192.168.20.15 = C0.A8.14.0F → little-endian = 0F14A8C0
        assert _hex_to_ip("0F14A8C0") == "192.168.20.15"

    def test_hex_to_port_http(self):
        assert _hex_to_port("0050") == 80

    def test_hex_to_port_postgres(self):
        assert _hex_to_port("1538") == 5432

    def test_hex_to_port_high(self):
        assert _hex_to_port("AE14") == 44564

    def test_hex_to_port_redis(self):
        assert _hex_to_port("18EB") == 6379


# ---------------------------------------------------------------------------
# /proc/net/tcp parser tests
# ---------------------------------------------------------------------------


class TestParseProcNetTcp:
    def test_parse_established_connections(self):
        raw = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 0F0012AC:1F40 0E0012AC:1E07 01 00000000:00000000 02:00000271 00000000     0        0 12345\n"
            "   1: 0F0012AC:1F40 0D0012AC:18EB 01 00000000:00000000 02:00000271 00000000     0        0 12346\n"
        )
        conns = parse_proc_net_tcp(raw, host="tmtdockp01")
        assert len(conns) == 2
        assert conns[0].src_ip == "172.18.0.15"
        assert conns[0].src_port == 8000
        assert conns[0].dst_ip == "172.18.0.14"
        assert conns[0].dst_port == 7687
        assert conns[0].host == "tmtdockp01"
        assert conns[1].dst_ip == "172.18.0.13"
        assert conns[1].dst_port == 6379

    def test_skip_non_established(self):
        raw = (
            "  sl  local_address rem_address   st\n"
            "   0: 0F0012AC:1F40 0E0012AC:1E07 0A\n"  # 0A = LISTEN
        )
        conns = parse_proc_net_tcp(raw)
        assert len(conns) == 0

    def test_skip_loopback(self):
        raw = (
            "  sl  local_address rem_address   st\n"
            "   0: 0100007F:1F40 0100007F:8000 01\n"  # 127.0.0.1 → 127.0.0.1
        )
        conns = parse_proc_net_tcp(raw)
        assert len(conns) == 0

    def test_empty_input(self):
        assert parse_proc_net_tcp("") == []
        assert parse_proc_net_tcp("\n\n") == []

    def test_header_only(self):
        raw = "  sl  local_address rem_address   st tx_queue rx_queue\n"
        conns = parse_proc_net_tcp(raw)
        assert len(conns) == 0

    def test_multiple_states(self):
        """Only ESTABLISHED (01) connections should be parsed."""
        raw = (
            "  sl  local_address rem_address   st\n"
            "   0: 0F0012AC:1F40 0E0012AC:1538 01\n"  # ESTABLISHED → keep
            "   1: 0F0012AC:1F40 0D0012AC:0050 06\n"  # TIME_WAIT → skip
            "   2: 0F0012AC:1F40 0C0012AC:18EB 01\n"  # ESTABLISHED → keep
            "   3: 00000000:1F40 00000000:0000 0A\n"  # LISTEN → skip
        )
        conns = parse_proc_net_tcp(raw)
        assert len(conns) == 2
        assert conns[0].dst_port == 5432
        assert conns[1].dst_port == 6379


# ---------------------------------------------------------------------------
# IP map collection tests
# ---------------------------------------------------------------------------


class TestCollectIpMap:
    @pytest.mark.asyncio
    async def test_collect_ip_map_from_networks(self):
        """Verify IP map is built from Docker network inspect response."""
        from src.discovery.collector import collect_ip_map

        mock_networks = [
            {
                "Name": "app_network",
                "Containers": {
                    "abc123": {"Name": "postgres", "IPv4Address": "172.18.0.3/16"},
                    "def456": {"Name": "redis", "IPv4Address": "172.18.0.4/16"},
                },
            },
            {
                "Name": "host",  # Should be skipped
                "Containers": {},
            },
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = mock_networks
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.discovery.collector._client_for_host", return_value=mock_client):
            ip_map = await collect_ip_map("testhost", "unix:///var/run/docker.sock")

        assert ip_map == {
            "172.18.0.3": "postgres",
            "172.18.0.4": "redis",
        }

    @pytest.mark.asyncio
    async def test_collect_ip_map_strips_cidr(self):
        """CIDR suffix is stripped from IP addresses."""
        from src.discovery.collector import collect_ip_map

        mock_networks = [
            {
                "Name": "overlay",
                "Containers": {
                    "a": {"Name": "svc", "IPv4Address": "10.0.0.5/24"},
                },
            },
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = mock_networks
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.discovery.collector._client_for_host", return_value=mock_client):
            ip_map = await collect_ip_map("host", "unix:///var/run/docker.sock")

        assert "10.0.0.5" in ip_map
        assert ip_map["10.0.0.5"] == "svc"

    @pytest.mark.asyncio
    async def test_collect_ip_map_skips_host_none_networks(self):
        """host and none networks should be skipped."""
        from src.discovery.collector import collect_ip_map

        mock_networks = [
            {"Name": "host", "Containers": {"a": {"Name": "svc", "IPv4Address": "10.0.0.1/24"}}},
            {"Name": "none", "Containers": {}},
            {"Name": "app", "Containers": {"b": {"Name": "app", "IPv4Address": "10.0.0.2/24"}}},
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = mock_networks
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.discovery.collector._client_for_host", return_value=mock_client):
            ip_map = await collect_ip_map("host", "unix:///var/run/docker.sock")

        # Only 'app' network containers should be in the map
        assert len(ip_map) == 1
        assert "10.0.0.2" in ip_map


# ---------------------------------------------------------------------------
# Collect endpoint API test
# ---------------------------------------------------------------------------


class TestCollectAPI:
    @pytest.fixture(autouse=True)
    def _mock_collector(self, monkeypatch):
        """Mock collector to avoid real Docker API calls."""
        monkeypatch.setattr("src.routers.discovery.graph_available", lambda: False)

    async def test_collect_no_hosts(self, client, monkeypatch):
        """Returns skipped when no Docker hosts configured."""
        monkeypatch.setattr("src.discovery.collector.DOCKER_HOSTS", {})

        resp = await client.post("/ops/discovery/collect", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"

    async def test_collect_with_hosts(self, client, monkeypatch):
        """Returns collection results when hosts are configured."""
        import src.discovery.collector as collector_mod

        monkeypatch.setattr(collector_mod, "DOCKER_HOSTS", {"testhost": "unix:///var/run/docker.sock"})

        async def mock_run_collection():
            return {
                "hosts": 1,
                "ip_map_size": 5,
                "raw_connections": 10,
                "resolved": 3,
                "unresolved": 7,
                "edges": 2,
                "summary": {"svc_a": [{"target": "svc_b", "port": 5432}]},
            }

        monkeypatch.setattr(collector_mod, "run_collection", mock_run_collection)

        resp = await client.post("/ops/discovery/collect", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["resolved"] == 3
        assert data["edges"] == 2


# ---------------------------------------------------------------------------
# MCP tool registration test
# ---------------------------------------------------------------------------


class TestMCPCollectorTools:
    async def test_collect_tool_registered(self, client):
        from src.mcp_endpoint import TOOL_DEFINITIONS as TOOLS

        tool_names = {t.name for t in TOOLS}
        assert "corvus_collect_connections" in tool_names

    async def test_tool_count_updated(self, client):
        from src.mcp_endpoint import TOOL_DEFINITIONS as TOOLS

        assert len(TOOLS) == 36
