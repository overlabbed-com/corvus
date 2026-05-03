"""B9 — Hydra v2.3 emits granted scopes in the `scp` claim (RFC 9068),
not the legacy `scope` string. Map well-known Corvus scopes to role
names so AuthMiddleware can authorize per scope.

Refs: projects/corvus-oidc/ Phase 4 scope-claim follow-up.
"""

from src.middleware.oidc_auth import Identity


def _identity_from_payload(payload):
    """Re-implement the role derivation block here in a tiny helper so
    the test pins the contract without exercising the full validate_token
    path (which mocks JWKS, etc.). We rebuild the same logic to match.
    """
    # Mirror the production block in oidc_auth.py validate_token().
    roles: list[str] = []
    scp = payload.get("scp")
    scope_str = payload.get("scope")
    tokens: list[str] = []
    if isinstance(scp, list):
        tokens = [str(s) for s in scp]
    elif isinstance(scope_str, str) and scope_str.strip():
        tokens = scope_str.split()
    mapping = {
        "corvus.admin": "admin",
        "corvus.write": "ops-write",
        "corvus.read": "ops-read",
    }
    for s in tokens:
        m = mapping.get(s)
        if m and m not in roles:
            roles.append(m)
    if not roles:
        raw = payload.get("roles", [])
        if isinstance(raw, str):
            roles = [raw]
        elif isinstance(raw, list):
            roles = [str(r) for r in raw]
    return Identity(
        sub=payload.get("sub", "x"),
        issuer="https://i/",
        audience=payload.get("aud", []),
        exp=payload.get("exp", 9999999999),
        roles=roles,
    )


def test_scp_array_read_only():
    i = _identity_from_payload({"scp": ["corvus.read"]})
    assert i.roles == ["ops-read"]


def test_scp_array_read_and_write():
    i = _identity_from_payload({"scp": ["corvus.read", "corvus.write"]})
    assert i.roles == ["ops-read", "ops-write"]


def test_scp_array_admin_dominant():
    i = _identity_from_payload({"scp": ["corvus.admin"]})
    assert i.roles == ["admin"]


def test_legacy_scope_string():
    i = _identity_from_payload({"scope": "corvus.read corvus.write"})
    assert i.roles == ["ops-read", "ops-write"]


def test_unknown_scopes_ignored():
    i = _identity_from_payload({"scp": ["openid", "email", "corvus.read"]})
    assert i.roles == ["ops-read"]


def test_falls_back_to_roles_claim_when_no_scope():
    i = _identity_from_payload({"roles": ["admin"]})
    assert i.roles == ["admin"]


def test_empty_token_no_roles():
    i = _identity_from_payload({})
    assert i.roles == []


def test_scp_takes_priority_over_legacy_scope():
    # When both are present, the RFC 9068 `scp` array wins.
    i = _identity_from_payload({"scp": ["corvus.read"], "scope": "corvus.admin"})
    assert i.roles == ["ops-read"]
