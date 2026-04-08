"""Authentication and authorization middleware.

Role-based API key auth with optional OIDC/JWT support.
When OIDC_ENABLED=true, JWT tokens are validated first, falling back to API keys.
Addresses threat model findings S1.1 (single token) and S1.2 (agent impersonation).

AuthMiddleware enforces authentication on ALL protected paths (/ops/, /backup/,
/agent-instructions) so individual routers don't need Depends(get_auth).
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from src.config import API_KEYS, OIDC_ENABLED
from src.middleware.oidc_auth import (
    Identity,
)

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)
_security_dependency = Security(security)

# Paths that never require authentication
PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/mcp",
})

# Path prefixes that require authentication
PROTECTED_PREFIXES = (
    "/ops/",
    "/backup/",
    "/agent-instructions",
)


class Role(StrEnum):
    ADMIN = "admin"
    OPS_WRITE = "ops-write"
    OPS_READ = "ops-read"
    AGENT = "agent"


# Role → permitted path prefixes and methods
ROLE_PERMISSIONS: dict[str, list[dict[str, Any]]] = {
    Role.ADMIN: [
        {"path": "/", "methods": ["GET", "POST", "PATCH", "DELETE"]},
    ],
    Role.OPS_WRITE: [
        {"path": "/ops/", "methods": ["GET", "POST", "PATCH"]},
    ],
    Role.OPS_READ: [
        {"path": "/ops/", "methods": ["GET"]},
    ],
    Role.AGENT: [
        {"path": "/ops/events", "methods": ["GET", "POST"]},
        {"path": "/ops/changes", "methods": ["GET", "POST", "PATCH"]},
        {"path": "/ops/incidents", "methods": ["GET", "POST", "PATCH"]},
        {"path": "/ops/problems", "methods": ["GET", "POST"]},
        {"path": "/ops/cmdb", "methods": ["GET", "POST"]},
        {"path": "/ops/discovery", "methods": ["GET", "POST"]},
        {"path": "/ops/graph", "methods": ["GET"]},
        {"path": "/ops/runbooks", "methods": ["GET", "POST"]},
        {"path": "/ops/health", "methods": ["GET"]},
        {"path": "/ops/metrics", "methods": ["GET"]},
        {"path": "/ops/knowledge", "methods": ["GET", "POST"]},
        {"path": "/ops/trust", "methods": ["GET"]},
        {"path": "/ops/gaps", "methods": ["GET", "POST"]},
        {"path": "/ops/triage", "methods": ["GET", "PATCH"]},
        {"path": "/ops/baselines", "methods": ["GET", "POST"]},
        {"path": "/ops/signal_quality", "methods": ["GET"]},
        {"path": "/ops/modules", "methods": ["GET"]},
        {"path": "/ops/cleanup", "methods": ["POST"]},
        {"path": "/agent-instructions", "methods": ["GET"]},
    ],
}


def _check_permission(role: str, path: str, method: str) -> bool:
    """Check if a role has permission for a path + method."""
    permissions = ROLE_PERMISSIONS.get(role, [])
    return any(path.startswith(perm["path"]) and method in perm["methods"] for perm in permissions)


class AuthContext:
    """Unified authentication context supporting both OIDC and API key auth."""

    def __init__(self, key_name: str, role: str, identity: Identity | None = None):
        self.key_name = key_name  # For backward compat: API key name
        self.role = role
        self._identity = identity  # OIDC Identity if JWT auth, None for API key

    @property
    def identity(self) -> str:
        if self._identity:
            return self._identity.identity
        return self.key_name

    @property
    def oidc_identity(self) -> Identity | None:
        return self._identity


def _extract_bearer_token(request: Request) -> str | None:
    """Extract bearer token from Authorization header."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def authenticate_request(request: Request) -> AuthContext | None:
    """Authenticate a request and return AuthContext, or None for errors.

    Priority order:
    1. OIDC/JWT validation if enabled
    2. API key validation (backward compat)

    Returns AuthContext on success.
    Raises HTTPException on auth failures.
    """
    from src.config import CORVUS_DEV_MODE

    # Dev mode: explicit flag allows everything
    if CORVUS_DEV_MODE:
        return AuthContext(key_name="anonymous", role=Role.ADMIN)

    # Production: no auth configured — log warning but deny access
    if not API_KEYS and not OIDC_ENABLED:
        import logging

        logging.getLogger(__name__).warning("No auth configured in production mode!")
        return None

    # Priority 1: OIDC/JWT auth if enabled
    if OIDC_ENABLED:
        try:
            from src.middleware.oidc_auth import get_oidc_config

            config = get_oidc_config()
            if config:
                token = _extract_bearer_token(request)
                if token:
                    try:
                        identity = config.validate_token(token)
                        # Map OIDC roles to local roles (extend as needed)
                        roles = identity.roles
                        role = Role.AGENT  # default
                        if "admin" in roles:
                            role = Role.ADMIN
                        elif "ops-write" in roles:
                            role = Role.OPS_WRITE
                        elif "ops-read" in roles:
                            role = Role.OPS_READ

                        logger.debug(f"OIDC authenticated: {identity} as {role}")
                        return AuthContext(
                            key_name=identity.sub,
                            role=role,
                            identity=identity,
                        )
                    except Exception as e:
                        logger.debug(f"OIDC validation failed: {e}")
                        # Fall through to API key auth
        except Exception as e:
            logger.debug(f"OIDC auth module error, falling back to API keys: {e}")

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
        role = Role.AGENT

    return AuthContext(key_name=key_name, role=role)


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce authentication on all protected paths.

    This middleware supports both OIDC/JWT and API key auth:
    - If OIDC_ENABLED=true and JWT provided: validate via OIDC provider
    - Otherwise: validate API key

    Ensures every /ops/ and /backup/ endpoint requires authentication.
    Auth context is stored in request.state.auth for downstream use.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Public paths — no auth required
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # Check if path requires protection
        needs_auth = any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)
        if not needs_auth:
            return await call_next(request)

        # Dev mode — allow all
        from src.config import CORVUS_DEV_MODE

        if CORVUS_DEV_MODE:
            request.state.auth = AuthContext(key_name="anonymous", role=Role.ADMIN)
            return await call_next(request)

        # Extract and validate token
        auth = authenticate_request(request)
        if auth is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authorization header"},
            )

        # Check role permissions
        if not _check_permission(auth.role, path, request.method):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Role '{auth.role}' cannot {request.method} {path}"},
            )

        # Store auth context for downstream use
        request.state.auth = auth
        return await call_next(request)


# Keep get_auth as a FastAPI Depends for routers that need explicit auth context
async def get_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = _security_dependency,
) -> AuthContext:
    """Extract and validate auth from request.

    When AuthMiddleware is active, this reads from request.state.auth.
    When used standalone (e.g., in tests), performs full validation.
    """
    # If middleware already authenticated, reuse context
    if hasattr(request.state, "auth"):
        return request.state.auth

    # Fallback: standalone auth (for backward compat)
    from src.config import CORVUS_DEV_MODE

    if CORVUS_DEV_MODE:
        return AuthContext(key_name="anonymous", role=Role.ADMIN)

    if not API_KEYS and not OIDC_ENABLED:
        return None

    # Try OIDC first if enabled
    if OIDC_ENABLED:
        try:
            token = _extract_bearer_token(request)
            if token:
                from src.middleware.oidc_auth import get_oidc_config

                config = get_oidc_config()
                if config:
                    identity = config.validate_token(token)
                    roles = identity.roles
                    role = Role.AGENT
                    if "admin" in roles:
                        role = Role.ADMIN
                    elif "ops-write" in roles:
                        role = Role.OPS_WRITE
                    elif "ops-read" in roles:
                        role = Role.OPS_READ

                    return AuthContext(
                        key_name=identity.sub,
                        role=role,
                        identity=identity,
                    )
        except Exception:
            logger.debug("OIDC token validation failed, falling back to API key auth")

    # API key auth
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = credentials.credentials
    key_entry = API_KEYS.get(token)
    if not key_entry:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if ":" in key_entry:
        key_name, role = key_entry.rsplit(":", 1)
    else:
        key_name = key_entry
        role = Role.AGENT

    if not _check_permission(role, request.url.path, request.method):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' cannot {request.method} {request.url.path}",
        )

    return AuthContext(key_name=key_name, role=role)
