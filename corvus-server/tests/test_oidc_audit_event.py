"""B2 audit-event tests — payload schema + no-leak negative assertion.

Reference: projects/corvus-oidc/reports/2026-05-01-corvus-server-oidc-bugs.md B2
            (Auditor N-01: must pin payload schema and assert no token leak)
            projects/corvus-oidc/reports/2026-05-01-architect-design-v2.md §3.5

The negative-assertion test guards against future refactors that might
accidentally serialise the JWT bytes into log records or audit-event
payloads. We embed a unique marker in the JWT and assert the marker never
appears in logs OR in the captured event payload.
"""

import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest

MARKER = "MARKERTOKENBYTES12345DONOTLEAK"


def _mint_marker_token() -> str:
    """A JWT whose payload contains the unique marker, so any code path
    that accidentally formats the token bytes (or unverified claims raw)
    into a log/event will be detected by substring match."""
    # nosemgrep: python.jwt.security.jwt-hardcode.jwt-python-hardcoded-secret
    # Test-only: the secret string is irrelevant — this token is meant to be
    # rejected by validation. We just need a syntactically-valid JWT that
    # carries our marker payload so we can grep it out of logs/events.
    return pyjwt.encode(
        {
            "sub": f"cc-test-{MARKER}",  # marker embedded in sub
            "iss": "https://hydra.example/",
            "aud": "corvus",
            "exp": int(time.time()) + 60,
        },
        "doesnt-matter-no-verify",
        algorithm="HS256",  # signing alg ignored — token is invalid
    )


@pytest.mark.asyncio
async def test_oidc_failed_event_payload_schema(client, monkeypatch):
    """Required fields land in the payload; optional fields are present
    when extractable."""
    from src.middleware import auth as auth_module
    from src.middleware.auth import authenticate_request

    monkeypatch.setattr(auth_module, "OIDC_STRICT", False)
    monkeypatch.setattr(auth_module, "OIDC_ENABLED", True)

    import src.config as config_module

    monkeypatch.setattr(config_module, "CORVUS_DEV_MODE", False)

    captured: list[dict] = []

    async def capture_event(*, event_type, severity, request, payload, target="corvus"):
        captured.append({"event_type": event_type, "severity": severity, "payload": payload})

    monkeypatch.setattr(auth_module, "_emit_auth_event", capture_event)

    token = _mint_marker_token()
    mock_request = MagicMock()
    mock_request.headers = {"authorization": f"Bearer {token}"}
    mock_request.state = MagicMock()
    mock_request.state.auth = None
    mock_request.url.path = "/ops/cmdb"
    mock_request.method = "GET"
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"

    monkeypatch.setattr(auth_module, "_extract_bearer_token", lambda req: token)

    with patch("src.middleware.oidc_auth.get_oidc_config") as mock_get_config:
        mock_oidc = MagicMock()
        mock_oidc.validate_token = AsyncMock(side_effect=Exception("not a valid signature"))
        mock_get_config.return_value = mock_oidc

        # Don't really await create_task'd helpers — call directly via patch.
        def fake_create_task(coro):
            # Schedule via the running loop — pytest-asyncio gives us one
            return auth_module.asyncio.ensure_future(coro)

        monkeypatch.setattr(auth_module.asyncio, "create_task", fake_create_task)

        await authenticate_request(mock_request)

        # Yield to allow scheduled tasks to run
        import asyncio as _asyncio

        await _asyncio.sleep(0.01)

    assert len(captured) == 1
    ev = captured[0]
    assert ev["event_type"] == "auth.oidc_validation_failed"
    assert ev["severity"] == "warning"

    p = ev["payload"]
    assert p["auth_method"] == "oidc"
    assert "error_class" in p
    assert p["path"] == "/ops/cmdb"
    assert p["method"] == "GET"
    assert "strict" in p
    # Unverified claims that the helper extracts:
    assert p.get("sub_unverified") == f"cc-test-{MARKER}"
    assert p.get("iss_unverified") == "https://hydra.example/"
    assert p.get("aud_unverified") == "corvus"


@pytest.mark.asyncio
async def test_oidc_failed_event_no_token_leak(client, monkeypatch, caplog):
    """N-01 negative-assertion: the JWT bytes MUST NOT appear in any log
    record or in the event payload (other than as the explicit
    sub_unverified extraction).

    The marker is embedded in the `sub` claim, so it's expected to appear
    in `sub_unverified`. We verify it does NOT appear anywhere else — not
    in any log message string, and not in any other payload field.
    """
    import logging

    from src.middleware import auth as auth_module
    from src.middleware.auth import authenticate_request

    monkeypatch.setattr(auth_module, "OIDC_STRICT", False)
    monkeypatch.setattr(auth_module, "OIDC_ENABLED", True)

    import src.config as config_module

    monkeypatch.setattr(config_module, "CORVUS_DEV_MODE", False)

    captured: list[dict] = []

    async def capture_event(*, event_type, severity, request, payload, target="corvus"):
        captured.append({"event_type": event_type, "severity": severity, "payload": payload})

    monkeypatch.setattr(auth_module, "_emit_auth_event", capture_event)

    token = _mint_marker_token()
    mock_request = MagicMock()
    mock_request.headers = {"authorization": f"Bearer {token}"}
    mock_request.state = MagicMock()
    mock_request.state.auth = None
    mock_request.url.path = "/ops/cmdb"
    mock_request.method = "GET"
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"

    monkeypatch.setattr(auth_module, "_extract_bearer_token", lambda req: token)

    with patch("src.middleware.oidc_auth.get_oidc_config") as mock_get_config:
        mock_oidc = MagicMock()
        # Exception WHOSE MESSAGE INCLUDES THE TOKEN — worst-case scenario.
        # B6 asserts we never format `e` into log messages, so this should NOT leak.
        mock_oidc.validate_token = AsyncMock(side_effect=Exception(f"OIDC failure detail: {token}"))
        mock_get_config.return_value = mock_oidc

        with caplog.at_level(logging.DEBUG, logger="src.middleware.auth"), contextlib.suppress(Exception):
            await authenticate_request(mock_request)

        import asyncio as _asyncio

        await _asyncio.sleep(0.01)

    # 1. Token bytes (the full JWT string) must NOT appear in log records.
    for record in caplog.records:
        rendered = record.getMessage()
        assert token not in rendered, (
            f"Token bytes leaked into log record: {record.name}/{record.levelname}: {rendered!r}"
        )
        # Even substring check: no contiguous JWT-shaped run.
        # The marker IS in the sub claim — but should not appear in raw form
        # in the log message itself (extra fields are OK).
        assert MARKER not in rendered, f"Token-derived MARKER leaked into log MESSAGE: {rendered!r}"

    # 2. The captured event payload may contain MARKER ONLY in sub_unverified.
    assert len(captured) == 1
    payload = captured[0]["payload"]
    for k, v in payload.items():
        if k == "sub_unverified":
            continue  # this is the explicit safe extraction
        if isinstance(v, str):
            assert MARKER not in v, f"MARKER leaked into payload[{k!r}]={v!r}"
            assert token not in v, f"Token bytes leaked into payload[{k!r}]"


@pytest.mark.asyncio
async def test_break_glass_key_emits_p1_event(client, monkeypatch):
    """Design v2.1 §3.6c — `auth.break_glass_used` event with severity
    critical when the break-glass key is used."""
    from src.middleware import auth as auth_module
    from src.middleware.auth import authenticate_request

    monkeypatch.setattr(auth_module, "OIDC_STRICT", True)
    monkeypatch.setattr(auth_module, "OIDC_ENABLED", False)

    import src.config as config_module

    monkeypatch.setattr(config_module, "CORVUS_DEV_MODE", False)

    break_glass_secret = "break-glass-secret-value"  # noqa: S105 — test fixture
    monkeypatch.setitem(auth_module.API_KEYS, break_glass_secret, "corvus-break-glass:agent")
    monkeypatch.setattr(auth_module, "OIDC_BREAK_GLASS_KEY_NAME", "corvus-break-glass")

    captured: list[dict] = []

    async def capture_event(*, event_type, severity, request, payload, target="corvus"):
        captured.append({"event_type": event_type, "severity": severity, "payload": payload})

    monkeypatch.setattr(auth_module, "_emit_auth_event", capture_event)

    mock_request = MagicMock()
    mock_request.headers = {"authorization": f"Bearer {break_glass_secret}"}
    mock_request.state = MagicMock()
    mock_request.state.auth = None
    mock_request.url.path = "/ops/cmdb"
    mock_request.method = "GET"
    mock_request.client = MagicMock()
    mock_request.client.host = "192.168.1.42"

    monkeypatch.setattr(auth_module, "_extract_bearer_token", lambda req: break_glass_secret)

    result = await authenticate_request(mock_request)
    import asyncio as _asyncio

    await _asyncio.sleep(0.01)

    assert result is not None
    assert result.key_name == "corvus-break-glass"

    assert any(e["event_type"] == "auth.break_glass_used" for e in captured)
    bg = next(e for e in captured if e["event_type"] == "auth.break_glass_used")
    assert bg["severity"] == "critical"
    assert bg["payload"]["key_name"] == "corvus-break-glass"
    # Secret value MUST NOT appear in payload
    for k, v in bg["payload"].items():
        if isinstance(v, str):
            assert break_glass_secret not in v, f"break-glass secret leaked into payload[{k!r}]"
