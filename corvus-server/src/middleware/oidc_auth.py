"""OIDC/JWT authentication middleware.

Replaces static API key auth with JWT-based identity from OIDC providers.
Supports Google, Azure AD, Okta, and any OIDC-compliant identity provider.
Provides backward compatibility via OIDC_ENABLED flag.

Threat model: S1.1 (single token) - JWT provides identity + claims + expiry.
S1.2 (agent impersonation) - JWT sub/jti enables traceability.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from src.config import OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_ENABLED, OIDC_ISSUER_URL

logger = logging.getLogger(__name__)

try:
    import jwt
    from jwt.exceptions import ExpiredSignatureError, InvalidTokenError, PyJWTError

    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger.warning("PyJWT not installed. OIDC auth will not function.")


class Identity:
    """OIDC identity extracted from JWT claims."""

    def __init__(self, sub: str, issuer: str, audience: str, exp: int, roles: list[str]):
        self.sub = sub  # Subject (unique user/service identifier)
        self.issuer = issuer  # OIDC issuer URL
        self.audience = audience  # Intended audience (client_id)
        self.exp = exp  # Expiration timestamp
        self.roles = roles  # Extracted from 'roles' claim if present

    @property
    def identity(self) -> str:
        return self.sub

    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return datetime.now(UTC).timestamp() > self.exp

    def __repr__(self) -> str:
        return f"Identity(sub={self.sub!r}, roles={self.roles})"


class OIDCConfig:
    """OIDC configuration with JWKS caching."""

    def __init__(
        self,
        issuer_url: str,
        client_id: str,
        client_secret: str,
    ):
        self.issuer_url = issuer_url
        self.client_id = client_id
        self.client_secret = client_secret
        self._jwks_cache: dict[str, list] = {}
        self._jwks_cache_time: float = 0
        self._jwks_cache_ttl = 3600  # Cache JWKS for 1 hour

    @property
    def discovery_url(self) -> str:
        """OIDC discovery endpoint."""
        return f"{self.issuer_url}/.well-known/openid-configuration"

    async def _resolve_jwks_url(self) -> str:
        """Resolve JWKS URL via the OIDC discovery document.

        B3 (replaces broken `_async_fetch_jwks_from_discovery` which used
        `anyio.open_file` on a URL — a filesystem API). Fail-fast on errors;
        do not silently return empty.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(self.discovery_url)
                resp.raise_for_status()
                data = resp.json()
            if "jwks_uri" not in data:
                raise ValueError("OIDC discovery document missing 'jwks_uri'")
            return data["jwks_uri"]
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            # Provider-specific fallbacks for issuers that we know.
            if "accounts.google.com" in self.issuer_url:
                return "https://www.googleapis.com/oauth2/v3/certs"
            if "login.microsoftonline.com" in self.issuer_url:
                tenant = self.issuer_url.split("/")[3]
                return f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
            raise

    async def fetch_jwks(self, *, force_refresh: bool = False) -> list[dict]:
        """Fetch and cache JWKS keys from issuer.

        B4 — `force_refresh=True` skips the cache (used on `kid` miss to
        absorb a Hydra signing-key rotation without the documented 1h
        blind window).
        """
        current_time = datetime.now(UTC).timestamp()

        if (
            not force_refresh
            and self._jwks_cache
            and current_time - self._jwks_cache_time < self._jwks_cache_ttl
        ):
            return self._jwks_cache

        jwks_url = await self._resolve_jwks_url()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(jwks_url)
                response.raise_for_status()
                jwks_data = response.json()
        except httpx.RequestError:
            # B6 — never log {e} in token-validation context (may transit token-derived material).
            logger.error(
                "Failed to fetch JWKS",
                extra={"jwks_url": jwks_url, "error_class": "RequestError"},
            )
            raise
        except json.JSONDecodeError:
            logger.error(
                "Invalid JSON in JWKS response",
                extra={"jwks_url": jwks_url, "error_class": "JSONDecodeError"},
            )
            raise

        keys = jwks_data.get("keys", [])
        if not keys:
            logger.error("Empty JWKS response", extra={"jwks_url": jwks_url})
            raise ValueError("No keys in JWKS response")

        self._jwks_cache = keys
        self._jwks_cache_time = current_time
        return keys

    async def get_key_for_token(self, token: str) -> Any:
        """Get the JWKS key matching the token's kid.

        B4 — async-coherent (no asyncio.run). On `kid` miss, refresh JWKS
        once before raising — closes the rotation blind window.
        """
        try:
            header = jwt.get_unverified_header(token)
        except PyJWTError:
            logger.warning(
                "Could not extract token header",
                extra={"error_class": "PyJWTError"},
            )
            raise

        if not header or "kid" not in header:
            raise ValueError("Token header missing kid")
        kid = header["kid"]

        for force_refresh in (False, True):
            keys = await self.fetch_jwks(force_refresh=force_refresh)
            for key_data in keys:
                if key_data.get("kid") == kid:
                    return jwt.PyJWK(key_data).key
            # First pass missed; force a refresh and try once more.

        raise ValueError(f"No matching key for kid: {kid}")

    async def validate_token(self, token: str, expected_audience: str | None = None) -> Identity:
        """Validate JWT token and return Identity.

        B1 — `expected_audience` defaults to `self.client_id`; `verify_aud`
        is unconditionally `True`. Callers that pass `None` get fail-safe
        audience checking against the configured client_id, not silent
        skip-of-audience.
        B4 — async-coherent.
        B6 — exception messages never leak token bytes into logs.
        """
        if not JWT_AVAILABLE:
            raise RuntimeError("PyJWT not installed")

        # B1 fail-safe default.
        audience = expected_audience or self.client_id
        if not audience:
            raise InvalidTokenError(
                "Cannot validate token: no audience configured (set OIDC_CLIENT_ID)"
            )

        try:
            key = await self.get_key_for_token(token)

            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,  # B1 — ALWAYS on
                    "require": ["exp", "iss", "sub", "aud"],
                },
                issuer=self.issuer_url,
                audience=audience,
            )
        except PyJWTError as e:
            # B6 — log error class only, not the exception message which
            # may contain token-derived material from chained exceptions.
            logger.warning(
                "JWT validation failed",
                extra={"error_class": type(e).__name__},
            )
            raise InvalidTokenError(type(e).__name__) from e
        except Exception as e:
            logger.error(
                "Unexpected error validating token",
                extra={"error_class": type(e).__name__},
            )
            raise InvalidTokenError(type(e).__name__) from e

        sub = payload.get("sub")
        if not sub:
            raise InvalidTokenError("Missing 'sub' claim")

        roles = payload.get("roles", [])
        if isinstance(roles, str):
            roles = [roles]

        identity = Identity(
            sub=sub,
            issuer=payload.get("iss") or self.issuer_url,
            audience=payload.get("aud") or [],
            exp=payload.get("exp"),
            roles=roles,
        )

        if identity.is_expired:
            raise ExpiredSignatureError("Token expired")

        return identity


# Singleton config instance
_oidc_config: OIDCConfig | None = None


def get_oidc_config() -> OIDCConfig | None:
    """Get configured OIDC config, or None if OIDC disabled."""
    global _oidc_config
    if _oidc_config is None:
        if not OIDC_ENABLED or not OIDC_ISSUER_URL:
            return None

        _oidc_config = OIDCConfig(
            issuer_url=OIDC_ISSUER_URL,
            client_id=OIDC_CLIENT_ID,
            client_secret=OIDC_CLIENT_SECRET,
        )
    return _oidc_config


# Paths that skip OIDC auth
OIDC_PUBLIC_PATHS = frozenset(
    {
        "/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/mcp/sse",
    }
)

# Prefixes that require OIDC auth
OIDC_PROTECTED_PREFIXES = ("/ops/", "/backup/", "/agent-instructions")


class OIDCAuthMiddleware(BaseHTTPMiddleware):
    """JWT/OIDC authentication middleware.

    Validates Bearer tokens against OIDC provider JWKS.
    Stores identity in request.state.identity for downstream use.
    Returns 401 for invalid/expired tokens.
    Falls back to API key auth if OIDC is disabled.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> JSONResponse | Response:
        path = request.url.path

        if path in OIDC_PUBLIC_PATHS:
            return await call_next(request)

        needs_auth = any(path.startswith(prefix) for prefix in OIDC_PROTECTED_PREFIXES)

        if not needs_auth:
            return await call_next(request)

        # Get OIDC config
        config = get_oidc_config()
        if config is None:
            # OIDC disabled - let API key auth handle it
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authorization header"},
            )

        token = auth_header[7:].strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authorization header"},
            )

        # Validate token
        try:
            identity = await config.validate_token(token, expected_audience=OIDC_CLIENT_ID)
            request.state.identity = identity
            logger.debug(f"Authenticated: {identity}")
        except (InvalidTokenError, ExpiredSignatureError, ValueError) as e:
            return JSONResponse(
                status_code=401,
                content={"detail": f"Invalid or expired token: {e}"},
            )
        except Exception as e:
            logger.error(f"Auth validation error: {e}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal authentication error"},
            )

        return await call_next(request)


async def oidc_verify_token(token: str) -> Identity:
    """Standalone function to validate a token (for use in tests or custom routes)."""
    config = get_oidc_config()
    if config is None:
        raise RuntimeError("OIDC not configured")

    return await config.validate_token(token, expected_audience=OIDC_CLIENT_ID)
