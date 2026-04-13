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

    @property
    def jwks_url(self) -> str:
        """JWKS endpoint - fetch from discovery if possible."""
        # Try to fetch from discovery endpoint
        try:
            # Use httpx.AsyncClient for async, fallback to sync for cache
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop:
                # We're in an async context
                import anyio

                with anyio.move_on_after(5):
                    response = anyio.run(self._async_fetch_jwks_from_discovery)
                    if response and "jwks_uri" in response:
                        return response["jwks_uri"]
            else:
                # Sync context
                import httpx

                try:
                    with httpx.Client() as client:
                        resp = client.get(self.discovery_url, timeout=5.0)
                        if resp.status_code == 200:
                            data = resp.json()
                            if "jwks_uri" in data:
                                return data["jwks_uri"]
                except Exception:
                    logger.debug("Failed to fetch JWKS URL from discovery endpoint")

            # Fallback: try common patterns
            if "accounts.google.com" in self.issuer_url:
                return "https://www.googleapis.com/oauth2/v3/certs"
            elif "login.microsoftonline.com" in self.issuer_url:
                tenant = self.issuer_url.split("/")[3]
                return f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
            elif "okta.com" in self.issuer_url:
                org_url = self.issuer_url.replace("/oauth2/default", "").replace("/oauth2", "")
                return f"{org_url}/.well-known/openid-configuration"

        except Exception as e:
            logger.debug(f"Could not fetch JWKS URL from discovery: {e}")

        # Last fallback - caller must provide jwks_uri
        return ""

    async def _async_fetch_jwks_from_discovery(self) -> dict:
        """Async fetch of discovery document."""
        import anyio

        async with anyio.create_task_group():
            results = {}

            async def fetch():
                async with anyio.open_file(self.discovery_url, "rb"):
                    pass

            return results

    async def fetch_jwks(self) -> list[dict]:
        """Fetch and cache JWKS keys from issuer."""
        current_time = datetime.now(UTC).timestamp()

        # Return cached if still valid
        if self._jwks_cache and current_time - self._jwks_cache_time < self._jwks_cache_ttl:
            return self._jwks_cache

        try:
            jwks_url = self.jwks_url
            if not jwks_url:
                raise ValueError("JWKS URL not available")

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(jwks_url)
                response.raise_for_status()
                jwks_data = response.json()

                keys = jwks_data.get("keys", [])
                if not keys:
                    raise ValueError("No keys in JWKS response")

                self._jwks_cache = keys
                self._jwks_cache_time = current_time
                return keys

        except httpx.RequestError as e:
            logger.error(f"Failed to fetch JWKS from {jwks_url}: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in JWKS response: {e}")
            raise
        except ValueError as e:
            logger.error(f"Invalid JWKS response: {e}")
            raise

    def get_key_for_token(self, token: str) -> Any:
        """Get the JWKS key matching the token's kid."""
        try:
            # Decode header without verification to get kid
            header = jwt.get_unverified_header(token)
            if not header or "kid" not in header:
                raise ValueError("Token header missing kid")

            kid = header["kid"]

            # Fetch JWKS and find matching key
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            keys = asyncio.run(self.fetch_jwks()) if loop else self._jwks_cache

            for key_data in keys:
                if key_data.get("kid") == kid:
                    # Convert JWK to PEM or use jwt directly
                    return jwt.PyJWK(key_data).key

            raise ValueError(f"No matching key for kid: {kid}")

        except PyJWTError as e:
            logger.debug(f"Error extracting key from token: {e}")
            raise

    def validate_token(self, token: str, expected_audience: str | None = None) -> Identity:
        """Validate JWT token and return Identity."""
        if not JWT_AVAILABLE:
            raise RuntimeError("PyJWT not installed")

        try:
            # Get the key for this token
            key = self.get_key_for_token(token)

            # Decode and validate
            options = {
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": expected_audience is not None,
                "require": ["exp", "iss", "sub"],
            }

            if expected_audience:
                options["audience"] = expected_audience

            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                options=options,
                issuer=self.issuer_url,
                audience=expected_audience if expected_audience else self.client_id,
            )

            # Extract claims
            sub = payload.get("sub")
            iss = payload.get("iss")
            aud = payload.get("aud")
            exp = payload.get("exp")
            roles = payload.get("roles", [])

            # Handle single role or list
            if isinstance(roles, str):
                roles = [roles]

            # Validate required claims
            if not sub:
                raise InvalidTokenError("Missing 'sub' claim")

            identity = Identity(
                sub=sub,
                issuer=iss or self.issuer_url,
                audience=aud or [],
                exp=exp,
                roles=roles,
            )

            if identity.is_expired:
                raise ExpiredSignatureError("Token expired")

            return identity

        except PyJWTError as e:
            logger.warning(f"JWT validation failed: {e}")
            raise InvalidTokenError(str(e)) from e
        except Exception as e:
            logger.error(f"Unexpected error validating token: {e}")
            raise InvalidTokenError(str(e)) from e


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
            identity = config.validate_token(token, expected_audience=OIDC_CLIENT_ID)
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

    return config.validate_token(token, expected_audience=OIDC_CLIENT_ID)
