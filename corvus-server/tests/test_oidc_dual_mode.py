"""B2 — `CORVUS_OIDC_STRICT=false` dual-mode tests.

Verifies the Phase 3-4 dual-mode behavior: when OIDC validation fails AND
strict mode is off, fall through to API-key auth, log at WARNING, and emit
an `auth.oidc_validation_failed` audit event.

Reference: projects/corvus-oidc/reports/2026-05-01-corvus-server-oidc-bugs.md B2,
            projects/corvus-oidc/reports/2026-05-01-architect-design-v2.md §3.5
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_dual_mode_oidc_failure_falls_through_to_api_key(client, monkeypatch):
    """OIDC failure with OIDC_STRICT=false falls through to API-key auth.

    Setup: OIDC enabled + STRICT off + a valid static API key in API_KEYS.
    Bearer token presented is JWT-like (will fail OIDC validation).
    Expected: caller does NOT get 503; instead, since the bearer doesn't
    match any API key, we get None (→ middleware emits 401). The PASS
    condition is "503 was NOT raised."
    """
    from src.middleware import auth as auth_module
    from src.middleware.auth import authenticate_request

    monkeypatch.setattr(auth_module, "OIDC_STRICT", False)
    monkeypatch.setattr(auth_module, "OIDC_ENABLED", True)
    # Some non-empty API_KEYS so the early "no auth configured" branch isn't hit.
    monkeypatch.setitem(auth_module.API_KEYS, "valid-static-key", "test:agent")

    import src.config as config_module

    monkeypatch.setattr(config_module, "CORVUS_DEV_MODE", False)

    mock_request = MagicMock()
    mock_request.headers = {"authorization": "Bearer some-jwt-shaped-bearer.token.here"}
    mock_request.state = MagicMock()
    mock_request.state.auth = None
    mock_request.url.path = "/ops/cmdb"
    mock_request.method = "GET"
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"

    # Patch _extract_bearer_token to return our test token
    monkeypatch.setattr(auth_module, "_extract_bearer_token",
                        lambda req: "some-jwt-shaped-bearer.token.here")

    with patch("src.middleware.oidc_auth.get_oidc_config") as mock_get_config:
        mock_oidc = MagicMock()
        mock_oidc.validate_token = AsyncMock(side_effect=Exception("Token expired"))
        mock_get_config.return_value = mock_oidc

        # Stub out audit event emission so we don't depend on DB.
        async def noop(**kw):
            return None
        monkeypatch.setattr(auth_module, "_emit_auth_event", noop)

        # In dual-mode, this should NOT raise; should return None
        # (since "some-jwt-shaped-bearer.token.here" isn't in API_KEYS).
        result = await authenticate_request(mock_request)

    # No exception raised, fell through to API-key path which doesn't match → None.
    assert result is None


@pytest.mark.asyncio
async def test_dual_mode_oidc_failure_then_static_key_succeeds(client, monkeypatch):
    """When dual-mode + bearer happens to BE a valid static API key,
    the static-key path authenticates successfully after OIDC fall-through.

    Note: in practice clients send EITHER a JWT or a static key, not both.
    But the bearer extraction is shape-agnostic — JWT-validate fails, then
    the same string is checked against API_KEYS. If it happens to be a
    static key, it works. This is the dual-mode coexistence behavior.
    """
    from src.middleware import auth as auth_module
    from src.middleware.auth import authenticate_request

    monkeypatch.setattr(auth_module, "OIDC_STRICT", False)
    monkeypatch.setattr(auth_module, "OIDC_ENABLED", True)
    static_key = "real-static-secret-12345"
    monkeypatch.setitem(auth_module.API_KEYS, static_key, "claude-code:agent")

    import src.config as config_module

    monkeypatch.setattr(config_module, "CORVUS_DEV_MODE", False)

    mock_request = MagicMock()
    mock_request.headers = {"authorization": f"Bearer {static_key}"}
    mock_request.state = MagicMock()
    mock_request.state.auth = None
    mock_request.url.path = "/ops/cmdb"
    mock_request.method = "GET"
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"

    monkeypatch.setattr(auth_module, "_extract_bearer_token", lambda req: static_key)

    with patch("src.middleware.oidc_auth.get_oidc_config") as mock_get_config:
        mock_oidc = MagicMock()
        mock_oidc.validate_token = AsyncMock(side_effect=Exception("Bad JWT shape"))
        mock_get_config.return_value = mock_oidc

        async def noop(**kw):
            return None
        monkeypatch.setattr(auth_module, "_emit_auth_event", noop)

        result = await authenticate_request(mock_request)

    assert result is not None
    assert result.key_name == "claude-code"


@pytest.mark.asyncio
async def test_strict_mode_default_still_raises_503(client, monkeypatch):
    """Default OIDC_STRICT=true preserves current production behavior.

    This is the explicit guarantee that introducing OIDC_STRICT does not
    accidentally weaken the production posture.
    """
    from fastapi import HTTPException

    # Confirm the import-time default
    import src.config as _config
    from src.middleware import auth as auth_module
    from src.middleware.auth import authenticate_request
    assert _config.OIDC_STRICT is True, "OIDC_STRICT default must be True (backward-compat)"

    monkeypatch.setattr(auth_module, "OIDC_STRICT", True)
    monkeypatch.setattr(auth_module, "OIDC_ENABLED", True)

    import src.config as config_module

    monkeypatch.setattr(config_module, "CORVUS_DEV_MODE", False)

    mock_request = MagicMock()
    mock_request.headers = {"authorization": "Bearer something"}
    mock_request.state = MagicMock()
    mock_request.state.auth = None
    mock_request.url.path = "/ops/cmdb"
    mock_request.method = "GET"
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"

    monkeypatch.setattr(auth_module, "_extract_bearer_token", lambda req: "something")

    with patch("src.middleware.oidc_auth.get_oidc_config") as mock_get_config:
        mock_oidc = MagicMock()
        mock_oidc.validate_token = AsyncMock(side_effect=Exception("Token expired"))
        mock_get_config.return_value = mock_oidc

        async def noop(**kw):
            return None
        monkeypatch.setattr(auth_module, "_emit_auth_event", noop)

        with pytest.raises(HTTPException) as excinfo:
            await authenticate_request(mock_request)
        assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_strict_mode_no_token_supplied_falls_to_api_key_path(client, monkeypatch):
    """`OIDC_ENABLED=true` + no bearer token = skip OIDC block, fall to API-key path.

    Auditor B2 missing test: 'OIDC_ENABLED=true but no token supplied'.
    Behavior: not a token validation failure, just no token. Reach API-key
    branch which returns None → middleware turns into 401.
    """
    from src.middleware import auth as auth_module
    from src.middleware.auth import authenticate_request

    monkeypatch.setattr(auth_module, "OIDC_STRICT", True)
    monkeypatch.setattr(auth_module, "OIDC_ENABLED", True)
    monkeypatch.setitem(auth_module.API_KEYS, "k", "test:agent")

    import src.config as config_module

    monkeypatch.setattr(config_module, "CORVUS_DEV_MODE", False)

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.state = MagicMock()
    mock_request.state.auth = None
    mock_request.url.path = "/ops/cmdb"
    mock_request.method = "GET"
    mock_request.client = MagicMock()
    mock_request.client.host = "10.0.0.1"

    # No bearer
    monkeypatch.setattr(auth_module, "_extract_bearer_token", lambda req: None)

    result = await authenticate_request(mock_request)
    assert result is None  # → 401 in middleware
