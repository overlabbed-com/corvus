"""Authentication and authorization middleware.

Role-based API key auth with optional OIDC/JWT support.
When OIDC_ENABLED=true, JWT tokens are validated first, falling back to API keys.
Addresses threat model findings S1.1 (single token) and S1.2 (agent impersonation).

AuthMiddleware enforces authentication on ALL protected paths (/ops/, /backup/,
/agent-instructions) so individual routers don't need Depends(get_auth).
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import jwt as _pyjwt
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from src.config import (
    API_KEYS,
    OIDC_BREAK_GLASS_KEY_NAME,
    OIDC_CLIENT_ID,
    OIDC_ENABLED,
    OIDC_STRICT,
)
from src.middleware.oidc_auth import (
    Identity,
)

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)
_security_dependency = Security(security)

# Paths that never require authentication
PUBLIC_PATHS = frozenset(
    {
        "/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/mcp/sse",
    }
)

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


# B6 — never include token bytes or substrings of length > 16 in any field.
# This is verified by tests/test_oidc_audit_event.py no-leak negative assertion.
def _safe_unverified_claims(token: str) -> dict[str, Any]:
    """Best-effort extraction of unverified claims for audit telemetry.

    Returns a dict with at most {"sub", "iss", "aud", "client_id"} when the
    token decodes; empty dict when it doesn't. Never includes raw token
    material — only short claim strings that are themselves bounded.
    """
    out: dict[str, Any] = {}
    try:
        # Intentional: claims are extracted ONLY for audit-log enrichment of an
        # already-rejected token (validation failed upstream). We never trust
        # these values for authn/authz — output keys are *_unverified and field
        # lengths are bounded below.
        unverified = _pyjwt.decode(  # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
            token, options={"verify_signature": False}
        )
    except Exception:
        return out
    for k_in, k_out in (
        ("sub", "sub_unverified"),
        ("iss", "iss_unverified"),
        ("aud", "aud_unverified"),
        ("client_id", "client_id_unverified"),
    ):
        v = unverified.get(k_in)
        if v is None:
            continue
        # Defense-in-depth: bound any single field length to 256 chars.
        if isinstance(v, str) and len(v) > 256:
            v = v[:256]
        out[k_out] = v
    return out


def _safe_kid(token: str) -> str | None:
    """Best-effort kid extraction for audit telemetry."""
    try:
        header = _pyjwt.get_unverified_header(token)
        kid = header.get("kid")
        if isinstance(kid, str) and len(kid) <= 256:
            return kid
    except Exception:
        return None
    return None


async def _emit_auth_event(
    *,
    event_type: str,
    severity: str,
    request: Request,
    payload: dict[str, Any],
    target: str = "corvus",
) -> None:
    """Fire-and-forget write of an auth event into ops_events.

    Used by the auth middleware for `auth.oidc_validation_failed` (B2) and
    `auth.break_glass_used` (design v2.1 §3.6c). Exceptions are swallowed
    so audit failures never break the auth path; logged at WARNING for
    operator visibility.
    """
    try:
        from src.database import get_db
        from src.event_signing import sign_event
        from src.sanitizer import sanitize

        event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(UTC).isoformat()
        sanitized = sanitize(json.dumps(payload))

        event_row = {
            "id": event_id,
            "timestamp": now,
            "source": "auth",
            "type": event_type,
            "target": target,
            "severity": severity,
            "data": payload,
        }
        signature = sign_event(event_row)

        db = await get_db()
        await db.execute(
            """INSERT INTO ops_events
               (id, timestamp, source, type, target, severity, data,
                related_incident_id, related_change_id, related_problem_id,
                parent_event_id, authenticated_as, signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)""",
            (
                event_id,
                now,
                "auth",
                event_type,
                target,
                severity,
                sanitized,
                payload.get("authenticated_as", "anonymous"),
                signature,
            ),
        )
        await db.commit()
    except Exception:
        logger.warning(
            "Failed to persist auth event",
            extra={"event_type": event_type, "severity": severity},
        )


async def authenticate_request(request: Request) -> AuthContext | None:
    """Authenticate a request and return AuthContext, or None for errors.

    Priority order:
    1. OIDC/JWT validation if enabled
    2. API key validation (backward compat / Phase 3-4 dual-mode)

    Returns AuthContext on success.
    Raises HTTPException(503) when OIDC validation fails AND OIDC_STRICT=true
    (Phase 5+, default). When OIDC_STRICT=false (Phase 3-4 dual-mode), falls
    through to API-key path with a logged WARNING and an
    `auth.oidc_validation_failed` audit event for observability.

    B1 — passes `expected_audience=OIDC_CLIENT_ID` to fail-safe audience checks.
    B2 — observable fall-through with audit event.
    B4 — async-coherent (was sync; cascades to AuthMiddleware.dispatch).
    """
    from src.config import CORVUS_DEV_MODE

    # Dev mode: explicit flag allows everything
    if CORVUS_DEV_MODE:
        return AuthContext(key_name="anonymous", role=Role.ADMIN)

    # Production: no auth configured — log warning but deny access
    if not API_KEYS and not OIDC_ENABLED:
        logger.warning("No auth configured in production mode!")
        return None

    # Priority 1: OIDC/JWT auth if enabled
    if OIDC_ENABLED:
        oidc_failed_event_payload: dict[str, Any] | None = None
        try:
            from src.middleware.oidc_auth import get_oidc_config

            config = get_oidc_config()
            if config:
                token = _extract_bearer_token(request)
                if token:
                    try:
                        # B1 — pass audience explicitly. validate_token now
                        # also defaults to self.client_id if missing, so this
                        # is belt-and-suspenders.
                        identity = await config.validate_token(
                            token, expected_audience=OIDC_CLIENT_ID
                        )
                        roles = identity.roles
                        role = Role.AGENT  # default
                        if "admin" in roles:
                            role = Role.ADMIN
                        elif "ops-write" in roles:
                            role = Role.OPS_WRITE
                        elif "ops-read" in roles:
                            role = Role.OPS_READ

                        logger.debug("OIDC authenticated as %s", role)
                        return AuthContext(
                            key_name=identity.sub,
                            role=role,
                            identity=identity,
                        )
                    except Exception as exc:
                        # B2 — log + emit audit event + decide via OIDC_STRICT.
                        # B6 — DO NOT format `exc` into log/event payloads.
                        logger.warning(
                            "OIDC validation failed",
                            extra={"error_class": type(exc).__name__},
                        )
                        oidc_failed_event_payload = {
                            "auth_method": "oidc",
                            "error_class": type(exc).__name__,
                            "kid": _safe_kid(token),
                            "path": request.url.path,
                            "method": request.method,
                            "strict": OIDC_STRICT,
                            **_safe_unverified_claims(token),
                        }
        except Exception as exc:
            logger.warning(
                "OIDC auth module error",
                extra={"error_class": type(exc).__name__},
            )
            oidc_failed_event_payload = {
                "auth_method": "oidc",
                "error_class": type(exc).__name__,
                "kid": None,
                "path": request.url.path,
                "method": request.method,
                "strict": OIDC_STRICT,
                "module_error": True,
            }

        if oidc_failed_event_payload is not None:
            # Fire-and-forget audit emission.
            asyncio.create_task(
                _emit_auth_event(
                    event_type="auth.oidc_validation_failed",
                    severity="warning",
                    request=request,
                    payload=oidc_failed_event_payload,
                )
            )
            if OIDC_STRICT:
                # B2 strict mode (Phase 5+, default): preserve current
                # production semantics — fail closed, do not fall through.
                raise HTTPException(
                    status_code=503,
                    detail="OIDC provider unavailable",
                )
            # OIDC_STRICT=false (Phase 3-4 dual-mode): fall through to API key path.

    # Priority 2: API key auth (backward compat / dual-mode fallback)
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
        # Map known admin names to ADMIN role
        role = Role.ADMIN if key_name.lower() == "admin" else Role.AGENT

    # Design v2.1 §3.6c — emit P1-severity event when break-glass key is used.
    if key_name == OIDC_BREAK_GLASS_KEY_NAME:
        asyncio.create_task(
            _emit_auth_event(
                event_type="auth.break_glass_used",
                severity="critical",
                request=request,
                payload={
                    "auth_method": "api_key",
                    "key_name": key_name,
                    "path": request.url.path,
                    "method": request.method,
                    "client_host": (
                        request.client.host if request.client else None
                    ),
                    "authenticated_as": key_name,
                },
            )
        )

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

        # Extract and validate token (B4 — now async)
        try:
            auth = await authenticate_request(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
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
                    # B1 — pass expected audience.
                    # B4 — await async validate_token.
                    identity = await config.validate_token(
                        token, expected_audience=OIDC_CLIENT_ID
                    )
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
        except Exception as exc:
            # B6 — no {exc} in token-validation log.
            logger.warning(
                "OIDC token validation failed in get_auth path",
                extra={"error_class": type(exc).__name__},
            )

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
