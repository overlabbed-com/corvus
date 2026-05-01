"""Story 5.3: Shared authentication logic.

Deduplicate auth logic between middleware and get_auth() function.
Previously, both had duplicated validation logic.
"""

import logging

from fastapi import HTTPException, Request

from src.config import API_KEYS, CORVUS_DEV_MODE, OIDC_ENABLED

logger = logging.getLogger(__name__)

# Re-export AuthContext and Role from auth.py for backward compatibility
from src.middleware.auth import AuthContext, Role, _check_permission, _extract_bearer_token

__all__ = [
    "AuthContext",
    "Role",
    "_check_permission",
    "_extract_bearer_token",
    "authenticate_request",
    "get_auth",
]


def authenticate_request(request: Request) -> AuthContext | None:
    """Authenticate a request and return AuthContext, or None for errors.

    This is the SHARED authentication function used by both:
    - AuthMiddleware.dispatch()
    - get_auth() (for backward compatibility)

    Priority order:
    1. OIDC/JWT validation if enabled
    2. API key validation (backward compat)

    Returns AuthContext on success.
    Raises HTTPException on auth failures in production.
    """
    # Dev mode: explicit flag allows everything
    if CORVUS_DEV_MODE:
        return AuthContext(key_name="anonymous", role=Role.ADMIN)

    # Production: no auth configured — log warning but deny access
    if not API_KEYS and not OIDC_ENABLED:
        logger.warning("No auth configured in production mode!")
        return None

    # Priority 1: OIDC/JWT auth if enabled
    if OIDC_ENABLED:
        try:
            from src.middleware.oidc_auth import Identity, get_oidc_config

            config = get_oidc_config()
            if config:
                token = _extract_bearer_token(request)
                if token:
                    try:
                        identity = config.validate_token(token)
                        # Map OIDC roles to local roles
                        roles = identity.roles if isinstance(identity, Identity) else getattr(identity, "roles", [])
                        role = Role.AGENT  # default
                        if "admin" in roles:
                            role = Role.ADMIN
                        elif "ops-write" in roles:
                            role = Role.OPS_WRITE
                        elif "ops-read" in roles:
                            role = Role.OPS_READ

                        logger.debug(f"OIDC authenticated: {identity} as {role}")
                        return AuthContext(
                            key_name=identity.sub if isinstance(identity, Identity) else str(identity),
                            role=role,
                            identity=identity if isinstance(identity, Identity) else None,
                        )
                    except Exception as e:
                        logger.error(f"OIDC validation failed: {e}")
                        if not CORVUS_DEV_MODE:
                            raise HTTPException(status_code=503, detail="OIDC provider unavailable")
                        # Fall through to API key auth in dev mode
        except Exception as e:
            logger.error(f"OIDC auth module error: {e}")
            if not CORVUS_DEV_MODE:
                raise HTTPException(status_code=503, detail="OIDC provider unavailable")
            # Fall through to API key auth in dev mode

    # Priority 2: API key auth (backward compat)
    token = _extract_bearer_token(request)
    if not token:
        return None

    key_entry = API_KEYS.get(token)
    if not key_entry:
        return None

    # Key entry format: "name:role" or just "name" (defaults to agent)
    if ":" in key_entry:
        key_name, role = key_entry.rsplit(":", 1)
    else:
        key_name = key_entry
        role = Role.ADMIN if key_name.lower() == "admin" else Role.AGENT

    return AuthContext(key_name=key_name, role=role)


async def get_auth(request: Request) -> AuthContext:
    """Extract and validate auth from request (FastAPI Depends).

    Story 5.3: Now delegates to shared authenticate_request() function.
    No longer duplicates logic from AuthMiddleware.

    When AuthMiddleware is active, this reads from request.state.auth.
    When used standalone (e.g., in tests), performs full validation.
    """
    # If middleware already authenticated, reuse context
    if hasattr(request.state, "auth"):
        return request.state.auth

    # Fallback: use shared authentication function
    auth = authenticate_request(request)
    if auth is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    # Check role permissions
    if not _check_permission(auth.role, request.url.path, request.method):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail=f"Role '{auth.role}' cannot {request.method} {request.url.path}",
        )

    return auth
