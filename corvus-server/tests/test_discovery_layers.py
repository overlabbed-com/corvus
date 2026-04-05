"""Tests for discovery layers 4-6: reported, inferred, elicited.

Since these endpoints require Neo4j, tests mock graph_session and
graph_available to verify endpoint logic without a live database.

The discovery router uses auth (Depends(get_auth)), so requests must
include the MCP internal key as a Bearer token.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from src.config import MCP_INTERNAL_KEY

# Auth headers for test requests (discovery endpoints require auth)
AUTH = {"Authorization": f"Bearer {MCP_INTERNAL_KEY}"}


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_graph():
    """Create mock graph_session and graph_available for discovery endpoints."""
    mock_session = AsyncMock()
    mock_session.run = AsyncMock()

    @asynccontextmanager
    async def mock_ctx():
        yield mock_session

    return mock_ctx, mock_session


async def _aiter(rows):
    for row in rows:
        yield row


# ---------------------------------------------------------------------------
# Layer 4: Reported
# ---------------------------------------------------------------------------


class TestLayer4Reported:
    """Tests for POST /ops/discovery/report."""

    @pytest.mark.asyncio
    async def test_report_services(self, client):
        """Report endpoint accepts service registrations."""
        mock_ctx, mock_session = _mock_graph()
        mock_session.run = AsyncMock(return_value=AsyncMock())

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/report",
                headers=AUTH,
                json={
                    "reporter": "nemoclaw",
                    "services": [
                        {"name": "vllm-primary", "host": "tmtdockp01", "service_type": "inference"},
                    ],
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["accepted"] is True
        assert data["reporter"] == "nemoclaw"
        assert data["stats"]["services"] == 1

    @pytest.mark.asyncio
    async def test_report_edges(self, client):
        """Report endpoint accepts dependency edges."""
        mock_ctx, mock_session = _mock_graph()
        mock_session.run = AsyncMock(return_value=AsyncMock())

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/report",
                headers=AUTH,
                json={
                    "reporter": "nemoclaw",
                    "edges": [
                        {"source": "sonarr", "target": "prowlarr", "type": "FEEDS", "confidence": 0.9},
                    ],
                },
            )

        assert resp.status_code == 201
        assert resp.json()["stats"]["edges"] == 1

    @pytest.mark.asyncio
    async def test_report_cis(self, client):
        """Report endpoint accepts CI registrations."""
        mock_ctx, mock_session = _mock_graph()
        mock_session.run = AsyncMock(return_value=AsyncMock())

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/report",
                headers=AUTH,
                json={
                    "reporter": "nemoclaw",
                    "cis": [
                        {
                            "type": "account",
                            "name": "astraweb-primary",
                            "service": "sabnzbd",
                            "properties": {"provider": "Astraweb", "expires_at": "2026-06-15"},
                        },
                    ],
                },
            )

        assert resp.status_code == 201
        assert resp.json()["stats"]["cis"] == 1

    @pytest.mark.asyncio
    async def test_report_empty_payload(self, client):
        """Report endpoint handles empty services/edges/cis gracefully."""
        mock_ctx, _ = _mock_graph()

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/report",
                headers=AUTH,
                json={"reporter": "test"},
            )

        assert resp.status_code == 201
        assert resp.json()["stats"] == {"services": 0, "edges": 0, "cis": 0}

    @pytest.mark.asyncio
    async def test_report_requires_reporter(self, client):
        """Report endpoint requires reporter field."""
        resp = await client.post(
            "/ops/discovery/report",
            headers=AUTH,
            json={"services": [{"name": "test"}]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_report_503_no_graph(self, client):
        """Returns 503 when graph is not available."""
        with patch("src.routers.discovery.graph_available", return_value=False):
            resp = await client.post(
                "/ops/discovery/report",
                headers=AUTH,
                json={"reporter": "test"},
            )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Layer 5: Inferred
# ---------------------------------------------------------------------------


class TestLayer5Inferred:
    """Tests for inference and suggestion endpoints."""

    @pytest.mark.asyncio
    async def test_infer_insufficient_history(self, client):
        """Inference returns gracefully when too few incidents exist."""
        mock_ctx, mock_session = _mock_graph()

        count_result = AsyncMock()
        count_result.single = AsyncMock(return_value={"cnt": 1})
        mock_session.run = AsyncMock(return_value=count_result)

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post("/ops/discovery/infer", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        assert data["inferred_edges"] == 0
        assert "Insufficient" in data["message"]

    @pytest.mark.asyncio
    async def test_infer_with_incidents(self, client):
        """Inference runs queries when enough incidents exist."""
        mock_ctx, mock_session = _mock_graph()

        call_count = [0]

        async def mock_run(query, **kwargs):
            call_count[0] += 1
            result = AsyncMock()
            if call_count[0] == 1:
                result.single = AsyncMock(return_value={"cnt": 10})
            elif call_count[0] == 2 or call_count[0] == 3:
                result.data = AsyncMock(return_value=[])
            else:
                result.data = AsyncMock(return_value=[])
            return result

        mock_session.run = mock_run

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post("/ops/discovery/infer", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_count"] == 10
        assert data["inferred_edges"] == 0

    @pytest.mark.asyncio
    async def test_suggestions_empty(self, client):
        """Suggestions endpoint returns empty list when no inferred edges."""
        mock_ctx, mock_session = _mock_graph()

        result = AsyncMock()
        result.__aiter__ = lambda self: _aiter([])
        mock_session.run = AsyncMock(return_value=result)

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.get("/ops/discovery/suggestions", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["suggestions"] == []

    @pytest.mark.asyncio
    async def test_validate_accept(self, client):
        """Validating a suggestion as valid upgrades it to DEPENDS_ON."""
        mock_ctx, mock_session = _mock_graph()

        check_result = AsyncMock()
        check_result.single = AsyncMock(return_value={"confidence": 0.4})
        upgrade_result = AsyncMock()
        calls = [check_result, upgrade_result]
        idx = [0]

        async def mock_run(query, **kwargs):
            i = idx[0]
            idx[0] += 1
            return calls[min(i, len(calls) - 1)]

        mock_session.run = mock_run

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/suggestions/svc-a/svc-b/validate",
                headers=AUTH,
                json={"valid": True, "notes": "Confirmed dependency"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "upgraded"
        assert data["source"] == "svc-a"
        assert data["target"] == "svc-b"

    @pytest.mark.asyncio
    async def test_validate_reject(self, client):
        """Validating a suggestion as invalid deletes it."""
        mock_ctx, mock_session = _mock_graph()

        check_result = AsyncMock()
        check_result.single = AsyncMock(return_value={"confidence": 0.4})
        delete_result = AsyncMock()
        calls = [check_result, delete_result]
        idx = [0]

        async def mock_run(query, **kwargs):
            i = idx[0]
            idx[0] += 1
            return calls[min(i, len(calls) - 1)]

        mock_session.run = mock_run

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/suggestions/svc-a/svc-b/validate",
                headers=AUTH,
                json={"valid": False},
            )

        assert resp.status_code == 200
        assert resp.json()["action"] == "rejected"

    @pytest.mark.asyncio
    async def test_validate_not_found(self, client):
        """Validating a nonexistent suggestion returns 404."""
        mock_ctx, mock_session = _mock_graph()

        check_result = AsyncMock()
        check_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=check_result)

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/suggestions/svc-x/svc-y/validate",
                headers=AUTH,
                json={"valid": True},
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Layer 6: Elicited
# ---------------------------------------------------------------------------


class TestLayer6Elicited:
    """Tests for knowledge capture endpoints."""

    @pytest.mark.asyncio
    async def test_report_knowledge(self, client):
        """Knowledge endpoint accepts dependency reports."""
        mock_ctx, mock_session = _mock_graph()
        mock_session.run = AsyncMock(return_value=AsyncMock())

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/knowledge",
                headers=AUTH,
                json={
                    "source": "claude-code:session",
                    "from_service": "caddy",
                    "to_service": "certbot",
                    "relationship": "DEPENDS_ON",
                    "notes": "Caddy depends on certbot with service_healthy condition.",
                    "confidence": 0.95,
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["accepted"] is True
        assert data["from_service"] == "caddy"
        assert data["to_service"] == "certbot"
        assert data["relationship"] == "DEPENDS_ON"
        assert data["layer"] == "elicited"

    @pytest.mark.asyncio
    async def test_report_knowledge_defaults(self, client):
        """Knowledge endpoint uses sensible defaults."""
        mock_ctx, mock_session = _mock_graph()
        mock_session.run = AsyncMock(return_value=AsyncMock())

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.post(
                "/ops/discovery/knowledge",
                headers=AUTH,
                json={
                    "source": "claude-code:session",
                    "from_service": "litellm",
                    "to_service": "vllm-primary",
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["confidence"] == 0.95
        assert data["relationship"] == "DEPENDS_ON"

    @pytest.mark.asyncio
    async def test_report_knowledge_requires_fields(self, client):
        """Knowledge endpoint requires source, from_service, to_service."""
        resp = await client.post(
            "/ops/discovery/knowledge",
            headers=AUTH,
            json={"source": "test"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_knowledge_empty(self, client):
        """Knowledge list returns empty when no elicited entries."""
        mock_ctx, mock_session = _mock_graph()

        result = AsyncMock()
        result.__aiter__ = lambda self: _aiter([])
        mock_session.run = AsyncMock(return_value=result)

        with (
            patch("src.routers.discovery.graph_available", return_value=True),
            patch("src.routers.discovery.graph_session", mock_ctx),
        ):
            resp = await client.get("/ops/discovery/knowledge", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["entries"] == []

    @pytest.mark.asyncio
    async def test_knowledge_503_no_graph(self, client):
        """Returns 503 when graph is not available."""
        with patch("src.routers.discovery.graph_available", return_value=False):
            resp = await client.post(
                "/ops/discovery/knowledge",
                headers=AUTH,
                json={
                    "source": "test",
                    "from_service": "a",
                    "to_service": "b",
                },
            )
        assert resp.status_code == 503
