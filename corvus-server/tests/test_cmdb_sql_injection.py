"""Tests for CMDB SQL injection prevention via field allowlist.

Story 1.4: All dynamic column names should be validated against
an allowlist before building SQL SET clauses.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_malicious_column_name_rejected(client):
    """Malicious column names should be rejected."""
    from src.routers.cmdb import _validate_update_fields
    from fastapi import HTTPException

    # Attempt SQL injection via column name
    malicious_fields = ["host", "'; DROP TABLE ops_cmdb; --"]

    with pytest.raises(HTTPException) as exc_info:
        _validate_update_fields(malicious_fields)

    assert exc_info.value.status_code == 400
    assert "Invalid field" in exc_info.value.detail


@pytest.mark.asyncio
async def test_valid_fields_pass_through(client):
    """Valid field names should pass through."""
    from src.routers.cmdb import _validate_update_fields

    valid_fields = ["host", "service_type", "critical"]

    result = _validate_update_fields(valid_fields)

    assert result == valid_fields


@pytest.mark.asyncio
async def test_attempted_injection_logged_as_security_event(client):
    """Attempted injection should be logged as a security event."""
    from src.routers.cmdb import _validate_update_fields
    import logging

    malicious_fields = ["host", "1=1"]

    with patch("src.routers.cmdb.logger") as mock_logger:
        with pytest.raises(Exception):
            _validate_update_fields(malicious_fields)

        # Should have logged at warning level
        assert mock_logger.warning.called


@pytest.mark.asyncio
async def test_all_valid_cmdb_fields_allowlisted(client):
    """All valid CMDB fields should be in the allowlist."""
    from src.routers.cmdb import VALID_UPDATE_FIELDS

    expected_fields = {"host", "service_type", "critical", "dependencies", "baseline_behavior", "alert_policy"}

    for field in expected_fields:
        assert field in VALID_UPDATE_FIELDS, f"Field {field} should be in allowlist"


@pytest.mark.asyncio
async def test_partial_malicious_fields_rejected(client):
    """If any field is malicious, the whole update should be rejected."""
    from src.routers.cmdb import _validate_update_fields

    # Mix of valid and invalid
    mixed_fields = ["host", "malicious_field"]

    with pytest.raises(Exception):
        _validate_update_fields(mixed_fields)