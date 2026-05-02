"""B1 — Audience enforcement tests.

Verifies that JWT validation enforces audience matching even when callers
omit the `expected_audience` argument. The fail-safe default is to validate
against `self.client_id` with `verify_aud=True`.

Reference: projects/corvus-oidc/reports/2026-05-01-corvus-server-oidc-bugs.md B1
"""

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import InvalidTokenError


def _gen_keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key()
    pem_priv = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pem_pub = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem_priv, pem_pub


def _mint(private_pem, *, aud, iss="https://hydra.example/", sub="cc-test", roles=None, kid="k1"):
    payload = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "exp": int(time.time()) + 3600,
        "roles": roles or ["agent"],
    }
    return pyjwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": kid})


@pytest.mark.asyncio
async def test_validate_token_rejects_wrong_audience(monkeypatch):
    """Token minted with aud=other-service must be rejected by Corvus."""
    from src.middleware.oidc_auth import OIDCConfig

    priv, pub = _gen_keypair()
    config = OIDCConfig(
        issuer_url="https://hydra.example/",
        client_id="corvus",
        client_secret="",
    )

    # Bypass JWKS fetch — return a single key matching kid=k1.
    async def fake_fetch_jwks(*, force_refresh=False):
        return [{"kid": "k1", "kty": "RSA", "_pem": pub}]

    async def fake_get_key(token):
        return pub  # PEM bytes work directly with PyJWT

    monkeypatch.setattr(config, "fetch_jwks", fake_fetch_jwks)
    monkeypatch.setattr(config, "get_key_for_token", fake_get_key)

    bad_token = _mint(priv, aud="other-service")
    with pytest.raises((InvalidTokenError, RuntimeError)):
        await config.validate_token(bad_token, expected_audience="corvus")


@pytest.mark.asyncio
async def test_validate_token_defaults_audience_to_client_id(monkeypatch):
    """B1 fail-safe: when caller omits expected_audience, validate_token
    defaults to self.client_id and STILL enforces aud (does not skip).

    Token minted for the WRONG audience must fail even when caller omits
    the expected_audience kwarg.
    """
    from src.middleware.oidc_auth import OIDCConfig

    priv, pub = _gen_keypair()
    config = OIDCConfig(
        issuer_url="https://hydra.example/",
        client_id="corvus",
        client_secret="",
    )

    async def fake_get_key(token):
        return pub

    monkeypatch.setattr(config, "get_key_for_token", fake_get_key)

    # Token's audience does NOT match self.client_id ("corvus").
    bad_token = _mint(priv, aud="some-other-app")

    # Caller omits expected_audience. Must still reject.
    with pytest.raises((InvalidTokenError, RuntimeError)):
        await config.validate_token(bad_token)


@pytest.mark.asyncio
async def test_validate_token_accepts_matching_audience(monkeypatch):
    from src.middleware.oidc_auth import OIDCConfig

    priv, pub = _gen_keypair()
    config = OIDCConfig(
        issuer_url="https://hydra.example/",
        client_id="corvus",
        client_secret="",
    )

    async def fake_get_key(token):
        return pub

    monkeypatch.setattr(config, "get_key_for_token", fake_get_key)

    good = _mint(priv, aud="corvus", roles=["ops-write"])
    identity = await config.validate_token(good, expected_audience="corvus")
    assert identity.sub == "cc-test"
    assert "ops-write" in identity.roles


@pytest.mark.asyncio
async def test_validate_token_no_client_id_configured_raises(monkeypatch):
    """If neither expected_audience nor client_id is configured, refuse."""
    from src.middleware.oidc_auth import OIDCConfig

    priv, _pub = _gen_keypair()
    config = OIDCConfig(issuer_url="https://hydra.example/", client_id="", client_secret="")
    token = _mint(priv, aud="something")
    with pytest.raises((InvalidTokenError, RuntimeError)):
        await config.validate_token(token)
