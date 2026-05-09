"""Tests for OIDC authentication fallback behavior.

Story 1.1: OIDC failures in production should raise HTTP 503, not silently fall back to API key.
Dev mode still allows fallback for testing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_oidc_failure_in_production_raises_503(client):
    """OIDC validation failure in production (non-dev mode) should raise HTTP 503."""
    from fastapi import HTTPException

    from src.config import CORVUS_DEV_MODE
    from src.middleware.auth import authenticate_request

    # Save original value
    original_dev_mode = CORVUS_DEV_MODE

    try:
        # Set production mode
        import src.config as config_module

        config_module.CORVUS_DEV_MODE = False

        # Clear API keys so we don't fall back to those either
        from src.middleware import auth as auth_module

        auth_module.API_KEYS.clear()
        config_module.API_KEYS.clear()

        # Create mock request with bearer token
        mock_request = MagicMock()
        mock_request.headers = {"authorization": "Bearer test-token"}
        mock_request.state = MagicMock()
        mock_request.state.auth = None

        # Patch OIDC to simulate failure
        with (
            patch.object(auth_module, "OIDC_ENABLED", True),
            patch.object(auth_module, "_extract_bearer_token", return_value="test-token"),
            patch("src.middleware.oidc_auth.get_oidc_config") as mock_get_config,
        ):
            # Make OIDC validation fail
            mock_oidc = MagicMock()
            mock_oidc.validate_token = AsyncMock(side_effect=Exception("Token expired"))
            mock_get_config.return_value = mock_oidc

            # In production mode with OIDC_STRICT=true (default),
            # OIDC failure should raise HTTP 503.
            with pytest.raises(HTTPException) as exc_info:
                await authenticate_request(mock_request)

            assert exc_info.value.status_code == 503
            assert "OIDC provider unavailable" in exc_info.value.detail
    finally:
        # Restore original value
        import src.config as config_module

        config_module.CORVUS_DEV_MODE = original_dev_mode


@pytest.mark.asyncio
async def test_oidc_failure_in_dev_mode_allows_fallback(client):
    """OIDC validation failure in dev mode should fall through to API key auth."""
    from src.config import CORVUS_DEV_MODE
    from src.middleware.auth import Role, authenticate_request

    # Save original value
    original_dev_mode = CORVUS_DEV_MODE

    try:
        # Set dev mode
        import src.config as config_module

        config_module.CORVUS_DEV_MODE = True

        # Create mock request with bearer token
        mock_request = MagicMock()
        mock_request.headers = {"authorization": "Bearer test-token"}
        mock_request.state = MagicMock()
        mock_request.state.auth = None

        # In dev mode, should return anonymous admin context without checking OIDC
        result = await authenticate_request(mock_request)

        assert result is not None
        assert result.role == Role.ADMIN
        assert result.key_name == "anonymous"
    finally:
        # Restore original value
        import src.config as config_module

        config_module.CORVUS_DEV_MODE = original_dev_mode


@pytest.mark.asyncio
async def test_oidc_validation_error_logged_at_warning_level(client):
    """OIDC validation errors should be logged at WARNING (not DEBUG, not ERROR).

    B2 (design v2.1) — WARNING is the right severity: failure is observable
    and Sentinel-alertable, but not a hard system error like a corrupted
    DB. Story 1.1's prior choice of ERROR is superseded by F-02.
    """
    from src.config import CORVUS_DEV_MODE
    from src.middleware.auth import authenticate_request

    # Save original value
    original_dev_mode = CORVUS_DEV_MODE

    try:
        # Set production mode
        import src.config as config_module

        config_module.CORVUS_DEV_MODE = False

        # Create mock request with bearer token
        mock_request = MagicMock()
        mock_request.headers = {"authorization": "Bearer test-token"}
        mock_request.state = MagicMock()
        mock_request.state.auth = None

        from src.middleware import auth as auth_module

        # Spy on logger
        with (
            patch.object(auth_module, "OIDC_ENABLED", True),
            patch.object(auth_module, "_extract_bearer_token", return_value="test-token"),
            patch("src.middleware.oidc_auth.get_oidc_config") as mock_get_config,
        ):
            # Make OIDC validation fail
            mock_oidc = MagicMock()
            mock_oidc.validate_token = AsyncMock(side_effect=Exception("Token expired"))
            mock_get_config.return_value = mock_oidc

            with patch.object(auth_module, "logger") as mock_logger:
                # Should raise HTTP 503, not silently fall back
                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await authenticate_request(mock_request)

                assert exc_info.value.status_code == 503
                # B2: log at WARNING (was ERROR pre-2026-05-01)
                assert mock_logger.warning.called
    finally:
        # Restore original value
        import src.config as config_module

        config_module.CORVUS_DEV_MODE = original_dev_mode


@pytest.mark.asyncio
async def test_oidc_module_error_in_production_raises_503(client):
    """OIDC module import/load error in production should raise HTTP 503."""
    from fastapi import HTTPException

    from src.config import CORVUS_DEV_MODE
    from src.middleware.auth import authenticate_request

    # Save original value
    original_dev_mode = CORVUS_DEV_MODE

    try:
        # Set production mode
        import src.config as config_module

        config_module.CORVUS_DEV_MODE = False

        from src.middleware import auth as auth_module

        # Create mock request with bearer token
        mock_request = MagicMock()
        mock_request.headers = {"authorization": "Bearer test-token"}
        mock_request.state = MagicMock()
        mock_request.state.auth = None

        # Patch to simulate OIDC module error
        with (
            patch.object(auth_module, "OIDC_ENABLED", True),
            patch.object(auth_module, "_extract_bearer_token", return_value="test-token"),
            patch(
                "src.middleware.oidc_auth.get_oidc_config",
                side_effect=Exception("OIDC configuration error"),
            ),
            patch.object(auth_module, "logger") as mock_logger,
        ):
            # Should raise HTTP 503, not silently fall back
            with pytest.raises(HTTPException) as exc_info:
                await authenticate_request(mock_request)

            assert exc_info.value.status_code == 503
            # B2: log at WARNING (was ERROR pre-2026-05-01)
            assert mock_logger.warning.called
    finally:
        # Restore original value
        import src.config as config_module

        config_module.CORVUS_DEV_MODE = original_dev_mode
