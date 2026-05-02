"""B3 + B4 — JWKS discovery (httpx) + async correctness + kid-miss refresh.

Reference: projects/corvus-oidc/reports/2026-05-01-corvus-server-oidc-bugs.md B3, B4
"""


import httpx
import pytest


@pytest.mark.asyncio
async def test_resolve_jwks_url_via_discovery(monkeypatch):
    """B3 — `_resolve_jwks_url` uses httpx, not anyio.open_file."""
    from src.middleware.oidc_auth import OIDCConfig

    config = OIDCConfig(issuer_url="https://hydra.example", client_id="corvus", client_secret="")

    async def fake_get(self, url, **kw):
        assert url == "https://hydra.example/.well-known/openid-configuration"
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json={
                "issuer": "https://hydra.example",
                "jwks_uri": "https://hydra.example/.well-known/jwks.json",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    url = await config._resolve_jwks_url()
    assert url == "https://hydra.example/.well-known/jwks.json"


def test_discovery_url_strips_trailing_slash():
    """B8 — issuer URLs that include a trailing slash (Ory Hydra and many
    other OIDC providers issue tokens whose `iss` has one) must not produce
    `//.well-known/...` when the discovery URL is composed. The well-known
    URL must always have exactly one slash before `.well-known`.
    """
    from src.middleware.oidc_auth import OIDCConfig

    with_slash = OIDCConfig(
        issuer_url="https://hydra.example/", client_id="c", client_secret=""
    )
    without_slash = OIDCConfig(
        issuer_url="https://hydra.example", client_id="c", client_secret=""
    )

    expected = "https://hydra.example/.well-known/openid-configuration"
    assert with_slash.discovery_url == expected
    assert without_slash.discovery_url == expected


@pytest.mark.asyncio
async def test_resolve_jwks_url_missing_jwks_uri(monkeypatch):
    """Discovery doc lacking jwks_uri is a hard error (no silent fall-through)."""
    from src.middleware.oidc_auth import OIDCConfig

    config = OIDCConfig(issuer_url="https://other.example", client_id="x", client_secret="")

    async def fake_get(self, url, **kw):
        request = httpx.Request("GET", url)
        return httpx.Response(200, json={"issuer": "https://other.example"}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises((ValueError, httpx.HTTPError)):
        await config._resolve_jwks_url()


@pytest.mark.asyncio
async def test_resolve_jwks_url_google_fallback(monkeypatch):
    """If discovery fails AND issuer is Google, use the well-known fallback."""
    from src.middleware.oidc_auth import OIDCConfig

    config = OIDCConfig(
        issuer_url="https://accounts.google.com",
        client_id="some-google-client",
        client_secret="",
    )

    async def fake_get(self, url, **kw):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    url = await config._resolve_jwks_url()
    assert url == "https://www.googleapis.com/oauth2/v3/certs"


@pytest.mark.asyncio
async def test_kid_miss_refreshes_jwks(monkeypatch):
    """B4 — when token's kid is not in cached JWKS, refresh once before raising."""
    from src.middleware.oidc_auth import OIDCConfig

    config = OIDCConfig(issuer_url="https://hydra.example/", client_id="corvus", client_secret="")

    fetch_calls: list[bool] = []

    # Pretend we have a token with kid=k2.
    # First fetch returns kid=k1 only; second (force_refresh=True) returns kid=k2.
    pem_pub = (
        b"-----BEGIN PUBLIC KEY-----\n"
        b"MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxxxxxxxxxxxxxxxxxxxx\n"
        b"-----END PUBLIC KEY-----\n"
    )

    async def fake_fetch(*, force_refresh=False):
        fetch_calls.append(force_refresh)
        if force_refresh:
            # After "rotation" — k2 now exists.
            return [{"kid": "k2", "kty": "RSA", "_test_pem": pem_pub}]
        return [{"kid": "k1", "kty": "RSA", "_test_pem": pem_pub}]

    monkeypatch.setattr(config, "fetch_jwks", fake_fetch)

    # Patch jwt.PyJWK to avoid real key parsing
    import jwt as pyjwt
    class FakePyJWK:
        def __init__(self, data):
            self.key = data["_test_pem"]
    monkeypatch.setattr(pyjwt, "PyJWK", FakePyJWK)
    # Patch jwt.get_unverified_header to return kid=k2
    monkeypatch.setattr(pyjwt, "get_unverified_header", lambda token: {"kid": "k2"})

    key = await config.get_key_for_token("any-token-doesnt-matter")
    assert key == pem_pub
    # Verify both calls happened — first cache, second force_refresh=True.
    assert fetch_calls == [False, True]


@pytest.mark.asyncio
async def test_kid_miss_after_refresh_still_misses_raises(monkeypatch):
    """If the kid is still not present after refresh, raise."""
    from src.middleware.oidc_auth import OIDCConfig

    config = OIDCConfig(issuer_url="https://hydra.example/", client_id="corvus", client_secret="")

    async def fake_fetch(*, force_refresh=False):
        return [{"kid": "k1", "kty": "RSA"}]

    monkeypatch.setattr(config, "fetch_jwks", fake_fetch)

    import jwt as pyjwt
    monkeypatch.setattr(pyjwt, "get_unverified_header", lambda token: {"kid": "k99"})

    with pytest.raises(ValueError, match="No matching key for kid"):
        await config.get_key_for_token("any-token")


def test_mcp_internal_key_required_in_production(monkeypatch):
    """B7 — production mode + MCP_ENABLED + no CORVUS_MCP_INTERNAL_KEY = startup error."""
    import importlib

    monkeypatch.setenv("CORVUS_DEV_MODE", "false")
    monkeypatch.setenv("CORVUS_MCP_ENABLED", "true")
    monkeypatch.delenv("CORVUS_MCP_INTERNAL_KEY", raising=False)

    import src.config as config_module

    with pytest.raises(RuntimeError, match="CORVUS_MCP_INTERNAL_KEY must be set"):
        importlib.reload(config_module)


def test_mcp_internal_key_optional_in_dev_mode(monkeypatch):
    """Dev mode tolerates missing CORVUS_MCP_INTERNAL_KEY (uses literal default)."""
    import importlib

    monkeypatch.setenv("CORVUS_DEV_MODE", "true")
    monkeypatch.setenv("CORVUS_MCP_ENABLED", "true")
    monkeypatch.delenv("CORVUS_MCP_INTERNAL_KEY", raising=False)

    import src.config as config_module
    importlib.reload(config_module)
    assert config_module.MCP_INTERNAL_KEY == "corvus-mcp-internal-dev"
