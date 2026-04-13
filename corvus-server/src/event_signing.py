"""Event signing — HMAC-SHA256 for audit-grade event integrity (GAP-8).

Every event stored in the ops DB gets a signature that proves:
1. The event was emitted by a valid Corvus API key
2. The event data has not been tampered with since emission

Signature = HMAC-SHA256(api_key_secret, event_id | timestamp | source | type | target | severity | data)
"""

import hashlib
import hmac
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Signing key — use CORVUS_SIGNING_KEY env var, or derive from API keys
_SIGNING_KEY = os.getenv("CORVUS_SIGNING_KEY", "")


def get_signing_key() -> str:
    """Get the HMAC signing key."""
    if _SIGNING_KEY:
        return _SIGNING_KEY
    # Fallback: derive from API keys (weakened but still useful)
    from src.config import API_KEYS

    if API_KEYS:
        # Use the first key as signing key (arbitrary but stable)
        return list(API_KEYS.keys())[0]
    return ""


def sign_event(event_row: dict[str, Any]) -> str:
    """Compute HMAC-SHA256 signature for an event row.

    The signature covers all meaningful fields to detect tampering.
    """
    key = get_signing_key()
    if not key:
        return ""

    # Build canonical string (deterministic field order)
    fields = [
        str(event_row.get("id", "")),
        str(event_row.get("timestamp", "")),
        str(event_row.get("source", "")),
        str(event_row.get("type", "")),
        str(event_row.get("target", "")),
        str(event_row.get("severity", "")),
        json.dumps(event_row.get("data", {}), sort_keys=True, default=str),
    ]
    message = "|".join(fields)
    signature = hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"v1={signature}"


def verify_signature(event_row: dict[str, Any]) -> bool:
    """Verify an event's HMAC signature.

    Returns True if signature is valid and event has not been tampered with.
    """
    stored_sig = event_row.get("signature", "")
    if not stored_sig:
        return False

    expected = sign_event(event_row)
    return hmac.compare_digest(stored_sig, expected)


def re_sign_events(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-sign a batch of events (e.g., after key rotation).

    Returns events with updated signatures.
    """
    return [{**row, "signature": sign_event(row)} for row in batch]
