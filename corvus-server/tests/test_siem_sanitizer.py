"""Test that SIEM forwarder sanitizes event data."""

import json

from src.sanitizer import sanitize


def test_siem_payload_sanitized():
    """Event data containing secrets should be sanitized before forwarding."""
    event_data = {
        "message": "Error connecting to postgres://admin:s3cret@db:5432/app",
        "evidences": [{"data": {"log": "Bearer my-secret-token in header"}}],
    }

    sanitized = sanitize(json.dumps(event_data))
    assert "s3cret" not in sanitized
    assert "my-secret-token" not in sanitized
    assert "[REDACTED]" in sanitized
