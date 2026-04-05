"""Tests for backup endpoints with security allowlists (E1.1, E1.2)."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import client  # noqa: F401


class TestBackupExec:
    """POST /backup/exec -- container command execution with allowlists."""

    @pytest.mark.asyncio
    async def test_allowed_command_accepted(self, client):
        """pg_dump on a postgres container should be accepted."""
        resp = await client.post(
            "/backup/exec",
            json={
                "container": "app-postgres",
                "command": ["pg_dump", "-U", "postgres", "mydb"],
            },
        )
        # May fail to actually connect (no Docker), but should not be 403
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_disallowed_command_rejected(self, client):
        """Arbitrary commands should be rejected."""
        resp = await client.post(
            "/backup/exec",
            json={
                "container": "app-postgres",
                "command": ["sh", "-c", "cat /etc/passwd"],
            },
        )
        assert resp.status_code == 403
        assert "not in command allowlist" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_disallowed_container_rejected(self, client):
        """Non-postgres containers should be rejected."""
        resp = await client.post(
            "/backup/exec",
            json={
                "container": "vllm-primary",
                "command": ["pg_dump", "-U", "postgres", "mydb"],
            },
        )
        assert resp.status_code == 403
        assert "not in container allowlist" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_shell_metacharacters_rejected(self, client):
        """Commands with shell metacharacters should be rejected."""
        resp = await client.post(
            "/backup/exec",
            json={
                "container": "app-postgres",
                "command": ["pg_dump", "-U", "postgres; rm -rf /"],
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_command_rejected(self, client):
        """Empty command list should be rejected."""
        resp = await client.post(
            "/backup/exec",
            json={
                "container": "app-postgres",
                "command": [],
            },
        )
        assert resp.status_code == 400
        assert "Empty command" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_container_metacharacters_rejected(self, client):
        """Container names with shell metacharacters should be rejected."""
        resp = await client.post(
            "/backup/exec",
            json={
                "container": "app-postgres; rm -rf /",
                "command": ["pg_dump", "-U", "postgres", "mydb"],
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_container_path_traversal_rejected(self, client):
        """Container names with path traversal should be rejected."""
        resp = await client.post(
            "/backup/exec",
            json={
                "container": "../../../etc/passwd",
                "command": ["pg_dump", "-U", "postgres", "mydb"],
            },
        )
        assert resp.status_code == 403


class TestBackupZfs:
    """POST /backup/zfs -- ZFS operations with allowlists."""

    @pytest.mark.asyncio
    async def test_allowed_zfs_command(self, client):
        """zpool status should be accepted."""
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["zpool", "status"],
            },
        )
        # May fail to actually run (no ZFS), but should not be 403
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_allowed_zfs_snapshot(self, client):
        """zfs snapshot should be accepted."""
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["zfs", "snapshot", "tank/data@backup-20260329"],
            },
        )
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_disallowed_command_rejected(self, client):
        """Non-ZFS commands should be rejected."""
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["sh", "-c", "cat /etc/shadow"],
            },
        )
        assert resp.status_code == 403
        assert "not in command allowlist" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_zfs_destroy_only_snapshots(self, client):
        """zfs destroy should only work on snapshots (contain @)."""
        # Snapshot destroy -- allowed
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["zfs", "destroy", "tank/data@old-snap"],
            },
        )
        assert resp.status_code != 403

        # Dataset destroy -- rejected
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["zfs", "destroy", "tank/data"],
            },
        )
        assert resp.status_code == 403
        assert "snapshot" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_shell_metacharacters_rejected(self, client):
        """Shell metacharacters in ZFS commands should be rejected."""
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["zfs", "list", "; rm -rf /"],
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_command_rejected(self, client):
        """Empty command list should be rejected."""
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": [],
            },
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_bare_zfs_command_rejected(self, client):
        """Bare 'zfs' without subcommand should be rejected."""
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["zfs"],
            },
        )
        assert resp.status_code == 400
        assert "Missing subcommand" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_bare_zpool_command_rejected(self, client):
        """Bare 'zpool' without subcommand should be rejected."""
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["zpool"],
            },
        )
        assert resp.status_code == 400
        assert "Missing subcommand" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_zfs_destroy_extra_args_rejected(self, client):
        """zfs destroy with extra arguments should be rejected."""
        resp = await client.post(
            "/backup/zfs",
            json={
                "command": ["zfs", "destroy", "tank@snap", "-r"],
            },
        )
        assert resp.status_code == 403
        assert "exactly one argument" in resp.json()["detail"]


class TestBackupAudit:
    """Audit logging for backup operations."""

    @pytest.mark.asyncio
    async def test_rejected_request_is_audited(self, client):
        """Rejected backup requests should be audited with result='rejected'."""
        with patch("src.routers.backup._audit_backup", new_callable=AsyncMock) as mock_audit:
            resp = await client.post(
                "/backup/exec",
                json={
                    "container": "app-postgres",
                    "command": ["sh", "-c", "cat /etc/passwd"],
                },
            )
            assert resp.status_code == 403
            mock_audit.assert_called_once()
            call_args = mock_audit.call_args
            details = call_args[0][2]
            assert details["result"] == "rejected"
            assert "reason" in details
