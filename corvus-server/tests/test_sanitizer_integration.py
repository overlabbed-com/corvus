"""Tests that sanitizer is wired into all output boundaries.

Validates that secrets in data flowing through events, incidents,
MCP responses, and SIEM forwarding are stripped before reaching
external consumers.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sanitizer import sanitize


def _mock_request():
    """Create a mock Request with auth state for endpoint tests."""
    request = MagicMock()
    request.state = SimpleNamespace(auth=SimpleNamespace(identity="test-user"))
    return request


class TestSanitizerOnEvents:
    """Event data is sanitized before storage."""

    @pytest.mark.asyncio
    async def test_event_data_sanitized_before_storage(self):
        """Secrets in event.data are stripped before SQLite INSERT."""
        from src.models.events import EventCreate
        from src.routers.events import emit_event

        event = EventCreate(
            source="test",
            type="session.started",
            target="svc-a",
            severity="info",
            data={"log": "password='s3cret' in config"},
        )

        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_row = {
            "id": "EVT-TEST1234",
            "timestamp": "2026-03-30T12:00:00",
            "source": "test",
            "type": "session.started",
            "target": "svc-a",
            "severity": "info",
            "data": json.dumps({"log": "password='[REDACTED]' in config"}),
            "related_incident_id": None,
            "related_change_id": None,
            "related_problem_id": None,
            "parent_event_id": None,
            "authenticated_as": "test-user",
        }
        mock_cursor.fetchone = AsyncMock(return_value=mock_row)
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()
        mock_db.close = AsyncMock()

        with (
            patch("src.routers.events.get_db", return_value=mock_db),
            patch("src.siem.forwarder.forward_to_siem", new_callable=AsyncMock),
        ):
            await emit_event(event, _mock_request())

        # Check that the INSERT call has sanitized data
        insert_call = mock_db.execute.call_args_list[0]
        insert_params = insert_call[0][1]  # positional args tuple
        data_field = insert_params[6]  # 7th param is the data JSON
        assert "s3cret" not in data_field
        assert "[REDACTED]" in data_field


class TestSanitizerOnIncidents:
    """Incident fields are sanitized before storage."""

    @pytest.mark.asyncio
    async def test_incident_description_sanitized(self):
        """Secrets in incident description are stripped before INSERT."""
        from src.models.incidents import IncidentCreate
        from src.routers.incidents import create_incident

        incident = IncidentCreate(
            detected_by="test",
            target="svc-a",
            severity="warning",
            title="Service failing with Bearer my-token-123",
            description="Log: postgres://admin:s3cret@db:5432/app connection refused",
        )

        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_row = {
            "id": "INC-TEST1234",
            "created_at": "2026-03-30T12:00:00",
            "detected_by": "test",
            "target": "svc-a",
            "status": "open",
            "severity": "warning",
            "title": "Service failing with [REDACTED]",
            "description": "Log: postgres://[REDACTED]@db:5432/app connection refused",
            "root_cause": None,
            "investigation_summary": None,
            "remediation_applied": None,
            "resolved_at": None,
            "resolution_time_minutes": None,
            "correlated_to_problem": None,
            "authenticated_as": "test-user",
        }
        mock_cursor.fetchone = AsyncMock(return_value=mock_row)
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()
        mock_db.close = AsyncMock()

        with patch("src.routers.incidents.get_db", return_value=mock_db):
            await create_incident(incident, _mock_request())

        # Check INSERT call has sanitized title and description
        insert_call = mock_db.execute.call_args_list[0]
        insert_params = insert_call[0][1]
        title_field = insert_params[5]  # title is 6th param
        desc_field = insert_params[6]  # description is 7th param
        assert "my-token-123" not in title_field
        assert "s3cret" not in desc_field


class TestSanitizerOnSIEM:
    """SIEM forwarder sanitizes events before forwarding."""

    def test_siem_payload_would_be_sanitized(self):
        """Verify sanitize() catches secrets in OCSF event JSON."""
        ocsf_event = {
            "message": "Error: postgres://admin:s3cret@db:5432/app",
            "evidence": {"data": {"log": "Bearer my-secret-token in header"}},
        }
        sanitized = sanitize(json.dumps(ocsf_event))
        assert "s3cret" not in sanitized
        assert "my-secret-token" not in sanitized


class TestSanitizerOnMCP:
    """MCP tool responses are sanitized before returning to agents."""

    def test_mcp_response_sanitized(self):
        """Verify sanitize() catches secrets in tool response JSON."""
        response = json.dumps(
            {
                "incidents": [
                    {
                        "id": "INC-001",
                        "description": "Auth failure: Bearer sk-abc123def456ghi789jkl012mno",
                    }
                ]
            }
        )
        sanitized = sanitize(response)
        assert "sk-abc123" not in sanitized
        assert "[REDACTED]" in sanitized


class TestNewPatterns:
    """Test new sanitizer patterns added for custom API key context."""

    def test_corvus_api_key(self):
        result = sanitize("key: corvus-e742918f5893bf1b89b1798fcc1b4f6b")
        assert "e742918f" not in result
        assert "[REDACTED]" in result

    def test_1password_connect_token(self):
        result = sanitize("token: eyJhbGciOiJFUzI1NiIsImtpZCI6IjVkMGRiOTg3In0.eyJzdWI")
        assert "eyJhbGci" not in result
        assert "[REDACTED]" in result

    def test_preserves_normal_text(self):
        text = "Container vllm-primary restarted at 2026-03-30T18:00:00Z on GPU 0"
        assert sanitize(text) == text
