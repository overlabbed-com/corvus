"""Tests for Layer 2: Observed discovery (network traffic)."""

import pytest

from src.config import MCP_INTERNAL_KEY
from src.discovery.observed import (
    ObservedConnection,
    RawConnection,
    connections_to_discovery_result,
    parse_conntrack,
    parse_tetragon_events,
    resolve_connections,
    summarize_connections,
)

AUTH = {"Authorization": f"Bearer {MCP_INTERNAL_KEY}"}


class TestParseConntrack:
    def test_parse_established_connections(self):
        raw = (
            "ipv4  2 tcp  6 300 ESTABLISHED "
            "src=172.20.0.5 dst=172.20.0.3 sport=44512 dport=5432 "
            "src=172.20.0.3 dst=172.20.0.5 sport=5432 dport=44512 [ASSURED]\n"
            "ipv4  2 tcp  6 300 ESTABLISHED "
            "src=172.20.0.5 dst=172.20.0.7 sport=33100 dport=6379 "
            "src=172.20.0.7 dst=172.20.0.5 sport=6379 dport=33100 [ASSURED]\n"
        )
        conns = parse_conntrack(raw, host="tmtdockp01")
        assert len(conns) == 2
        assert conns[0].src_ip == "172.20.0.5"
        assert conns[0].dst_ip == "172.20.0.3"
        assert conns[0].dst_port == 5432
        assert conns[0].host == "tmtdockp01"
        assert conns[1].dst_port == 6379

    def test_skip_non_established(self):
        raw = "ipv4  2 tcp  6 120 TIME_WAIT src=172.20.0.5 dst=172.20.0.3 sport=44512 dport=5432\n"
        conns = parse_conntrack(raw)
        assert len(conns) == 0

    def test_skip_non_tcp(self):
        raw = "ipv4  2 udp  17 30 src=172.20.0.5 dst=172.20.0.3 sport=44512 dport=53 ESTABLISHED\n"
        conns = parse_conntrack(raw)
        assert len(conns) == 0

    def test_empty_input(self):
        assert parse_conntrack("") == []
        assert parse_conntrack("\n\n") == []

    def test_first_direction_only(self):
        """conntrack shows both directions — we only capture the first occurrence of src/dst."""
        raw = (
            "ipv4  2 tcp  6 300 ESTABLISHED "
            "src=172.20.0.5 dst=172.20.0.3 sport=44512 dport=5432 "
            "src=172.20.0.3 dst=172.20.0.5 sport=5432 dport=44512\n"
        )
        conns = parse_conntrack(raw)
        assert len(conns) == 1
        # Should be the original direction (first src/dst)
        assert conns[0].src_ip == "172.20.0.5"
        assert conns[0].dst_ip == "172.20.0.3"


class TestParseTetragonEvents:
    def test_parse_kprobe_event(self):
        events = [
            {
                "process_kprobe": {
                    "process": {"binary": "/usr/bin/python3"},
                    "args": [
                        {
                            "sock_arg": {
                                "family": "AF_INET",
                                "saddr": "172.20.0.5",
                                "daddr": "172.20.0.3",
                                "sport": 44512,
                                "dport": 5432,
                            }
                        }
                    ],
                },
                "time": "2026-03-30T12:00:00Z",
            }
        ]
        conns = parse_tetragon_events(events, host="tmtdockp01")
        assert len(conns) == 1
        assert conns[0].src_ip == "172.20.0.5"
        assert conns[0].dst_port == 5432
        assert conns[0].host == "tmtdockp01"

    def test_skip_non_inet(self):
        events = [
            {
                "process_kprobe": {
                    "process": {"binary": "/usr/bin/python3"},
                    "args": [
                        {
                            "sock_arg": {
                                "family": "AF_UNIX",
                                "saddr": "",
                                "daddr": "",
                            }
                        }
                    ],
                }
            }
        ]
        conns = parse_tetragon_events(events)
        assert len(conns) == 0

    def test_skip_non_kprobe(self):
        events = [{"process_exec": {"process": {"binary": "/bin/sh"}}}]
        conns = parse_tetragon_events(events)
        assert len(conns) == 0

    def test_empty_events(self):
        assert parse_tetragon_events([]) == []


class TestResolveConnections:
    def test_resolve_known_ips(self):
        ip_map = {
            "172.20.0.5": "litellm",
            "172.20.0.3": "postgres",
        }
        raw = [
            RawConnection(src_ip="172.20.0.5", src_port=44512, dst_ip="172.20.0.3", dst_port=5432),
        ]
        result = resolve_connections(raw, ip_map)
        assert len(result.connections) == 1
        assert result.connections[0].source == "litellm"
        assert result.connections[0].target == "postgres"
        assert result.connections[0].dst_port == 5432
        assert len(result.unresolved) == 0

    def test_unresolved_ips(self):
        ip_map = {"172.20.0.5": "litellm"}
        raw = [
            RawConnection(src_ip="172.20.0.5", src_port=44512, dst_ip="10.0.0.1", dst_port=443),
        ]
        result = resolve_connections(raw, ip_map)
        assert len(result.connections) == 0
        assert len(result.unresolved) == 1

    def test_skip_self_connections(self):
        ip_map = {"172.20.0.5": "litellm"}
        raw = [
            RawConnection(src_ip="172.20.0.5", src_port=44512, dst_ip="172.20.0.5", dst_port=8080),
        ]
        result = resolve_connections(raw, ip_map)
        assert len(result.connections) == 0
        assert len(result.unresolved) == 0

    def test_deduplication(self):
        ip_map = {
            "172.20.0.5": "litellm",
            "172.20.0.3": "postgres",
        }
        raw = [
            RawConnection(src_ip="172.20.0.5", src_port=44512, dst_ip="172.20.0.3", dst_port=5432),
            RawConnection(src_ip="172.20.0.5", src_port=44513, dst_ip="172.20.0.3", dst_port=5432),
            RawConnection(src_ip="172.20.0.5", src_port=44514, dst_ip="172.20.0.3", dst_port=5432),
        ]
        result = resolve_connections(raw, ip_map)
        assert len(result.connections) == 1
        assert result.connections[0].count == 3


class TestConnectionsToDiscoveryResult:
    def test_creates_edges(self):
        conns = [
            ObservedConnection(
                source="litellm",
                target="postgres",
                dst_port=5432,
                count=10,
                first_seen="2026-03-30T12:00:00Z",
                last_seen="2026-03-30T12:05:00Z",
            ),
        ]
        result = connections_to_discovery_result(conns)
        assert len(result.edges) == 1
        edge = result.edges[0]
        assert edge["source"] == "litellm"
        assert edge["target"] == "postgres"
        assert edge["type"] == "OBSERVED_CONNECTION"
        assert edge["layer"] == "observed"
        assert edge["confidence"] == 0.8
        assert edge["dst_port"] == 5432
        assert edge["count"] == 10

    def test_dedup_edges(self):
        """Multiple connections same pair → single edge."""
        conns = [
            ObservedConnection(source="a", target="b", dst_port=5432, count=5),
            ObservedConnection(source="a", target="b", dst_port=6379, count=3),
        ]
        result = connections_to_discovery_result(conns)
        # Should deduplicate to one edge per (source, target) pair
        assert len(result.edges) == 1

    def test_empty_input(self):
        result = connections_to_discovery_result([])
        assert len(result.edges) == 0


class TestSummarizeConnections:
    def test_groups_by_source(self):
        conns = [
            ObservedConnection(source="litellm", target="postgres", dst_port=5432, count=10),
            ObservedConnection(source="litellm", target="redis", dst_port=6379, count=5),
            ObservedConnection(source="open-webui", target="litellm", dst_port=4000, count=20),
        ]
        summary = summarize_connections(conns)
        assert "litellm" in summary
        assert len(summary["litellm"]) == 2
        assert "open-webui" in summary
        assert len(summary["open-webui"]) == 1


class TestObservedAPI:
    """Test the /ops/discovery/connections endpoint."""

    @pytest.fixture(autouse=True)
    def _mock_graph(self, monkeypatch):
        """Mock graph operations for API tests."""
        from unittest.mock import AsyncMock, MagicMock

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=AsyncMock(data=AsyncMock(return_value=[])))

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("src.routers.discovery.graph_available", lambda: True)
        monkeypatch.setattr("src.routers.discovery.graph_session", lambda: mock_ctx)
        self.mock_session = mock_session

    async def test_ingest_tuples(self, client):
        resp = await client.post(
            "/ops/discovery/connections",
            headers=AUTH,
            json={
                "format": "tuples",
                "host": "tmtdockp01",
                "connections": [
                    {"src_ip": "172.20.0.5", "dst_ip": "172.20.0.3", "dst_port": 5432},
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["accepted"] is True

    async def test_ingest_conntrack(self, client):
        raw = (
            "ipv4  2 tcp  6 300 ESTABLISHED "
            "src=172.20.0.5 dst=172.20.0.3 sport=44512 dport=5432 "
            "src=172.20.0.3 dst=172.20.0.5 sport=5432 dport=44512\n"
        )
        resp = await client.post(
            "/ops/discovery/connections",
            headers=AUTH,
            json={
                "format": "conntrack",
                "host": "tmtdockp01",
                "raw_text": raw,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["accepted"] is True

    async def test_ingest_empty(self, client):
        resp = await client.post(
            "/ops/discovery/connections",
            headers=AUTH,
            json={"format": "tuples", "connections": []},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["resolved"] == 0
        assert "No connections" in data["message"]

    async def test_list_connections(self, client):
        from unittest.mock import AsyncMock

        # Mock graph query result with proper async iterator
        async def _empty_aiter(self):
            return
            yield  # noqa: RET504 — make this an async generator

        mock_result = AsyncMock()
        mock_result.__aiter__ = _empty_aiter
        self.mock_session.run = AsyncMock(return_value=mock_result)

        resp = await client.get("/ops/discovery/connections", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "connections" in data
        assert data["count"] == 0


class TestMCPObservedTools:
    """Verify MCP tool registration for Layer 2."""

    async def test_tools_registered(self, client):
        # Verify the tool names exist in the tool list
        from src.mcp_endpoint import TOOL_DEFINITIONS as TOOLS

        tool_names = {t.name for t in TOOLS}
        assert "corvus_observe_connections" in tool_names
        assert "corvus_list_connections" in tool_names

    async def test_tool_count_updated(self, client):
        from src.mcp_endpoint import TOOL_DEFINITIONS as TOOLS

        assert len(TOOLS) == 36  # 33 + 3 Layer 2 tools (observe, list, collect)
