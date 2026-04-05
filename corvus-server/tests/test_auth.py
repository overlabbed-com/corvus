"""Tests for auth middleware."""

from src.middleware.auth import AuthContext, Role, _check_permission


def test_admin_can_do_anything():
    assert _check_permission(Role.ADMIN, "/ops/changes", "POST")
    assert _check_permission(Role.ADMIN, "/ops/cmdb/test", "PATCH")
    assert _check_permission(Role.ADMIN, "/anything", "DELETE")


def test_ops_write_can_read_and_write():
    assert _check_permission(Role.OPS_WRITE, "/ops/changes", "GET")
    assert _check_permission(Role.OPS_WRITE, "/ops/changes", "POST")
    assert _check_permission(Role.OPS_WRITE, "/ops/incidents/INC-1", "PATCH")


def test_ops_write_cannot_delete():
    assert not _check_permission(Role.OPS_WRITE, "/ops/changes/CHG-1", "DELETE")


def test_ops_read_can_only_get():
    assert _check_permission(Role.OPS_READ, "/ops/events", "GET")
    assert not _check_permission(Role.OPS_READ, "/ops/events", "POST")
    assert not _check_permission(Role.OPS_READ, "/ops/changes", "PATCH")


def test_agent_scoped_access():
    assert _check_permission(Role.AGENT, "/ops/events", "GET")
    assert _check_permission(Role.AGENT, "/ops/events", "POST")
    assert _check_permission(Role.AGENT, "/ops/changes", "POST")
    assert _check_permission(Role.AGENT, "/ops/cmdb/register", "POST")
    assert _check_permission(Role.AGENT, "/ops/health", "GET")


def test_auth_context():
    ctx = AuthContext(key_name="test-agent", role=Role.AGENT)
    assert ctx.identity == "test-agent"
    assert ctx.role == Role.AGENT
