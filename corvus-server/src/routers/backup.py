"""Backup endpoints with security allowlists.

Addresses threat model findings:
- E1.1: /backup/exec arbitrary command execution
- E1.2: /backup/zfs arbitrary privileged commands

Every command is validated against an allowlist before execution.
Every call is audit-logged regardless of success or failure.
"""

import fnmatch
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backup", tags=["backup"])

# --- Allowlists ---

ALLOWED_EXEC_COMMANDS = {"pg_dump", "psql", "pg_restore"}
ALLOWED_EXEC_CONTAINERS = ["*-postgres"]  # fnmatch patterns
ALLOWED_ZFS_COMMANDS = {"zpool", "zfs"}
ALLOWED_ZFS_SUBCOMMANDS = {
    "zpool": {"status", "list", "get"},
    "zfs": {"list", "snapshot", "destroy", "get"},
}

# Safe characters allowlist for command arguments.
# Covers legitimate pg_dump flags, database names, ZFS dataset/snapshot names.
SAFE_ARG_CHARS = re.compile(r"^[a-zA-Z0-9_./@:=-]+$")

# Safe identifier for container names (Docker container name rules).
SAFE_CONTAINER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")


# --- Models ---


class ExecRequest(BaseModel):
    container: str
    command: list[str]


class ZfsRequest(BaseModel):
    command: list[str]


class BackupResponse(BaseModel):
    status: str
    message: str
    output: str | None = None


# --- Validation helpers ---


def _validate_no_metacharacters(args: list[str]) -> None:
    """Reject any argument not matching the safe-character allowlist."""
    for arg in args:
        if not SAFE_ARG_CHARS.match(arg):
            raise HTTPException(
                status_code=403,
                detail="Argument contains disallowed characters",
            )


def _validate_exec(container: str, command: list[str]) -> None:
    """Validate container exec request against allowlists."""
    if not command:
        raise HTTPException(status_code=400, detail="Empty command")

    # Validate container name is a safe identifier (no path traversal or metacharacters)
    if not SAFE_CONTAINER_NAME.match(container):
        raise HTTPException(
            status_code=403,
            detail="Container name contains disallowed characters",
        )

    # Also validate container args via allowlist
    _validate_no_metacharacters([container])

    # Check command allowlist
    if command[0] not in ALLOWED_EXEC_COMMANDS:
        raise HTTPException(
            status_code=403,
            detail=f"Command '{command[0]}' not in command allowlist. Allowed: {sorted(ALLOWED_EXEC_COMMANDS)}",
        )

    # Check container allowlist
    if not any(fnmatch.fnmatch(container, pat) for pat in ALLOWED_EXEC_CONTAINERS):
        raise HTTPException(
            status_code=403,
            detail=f"Container '{container}' not in container allowlist. Allowed patterns: {ALLOWED_EXEC_CONTAINERS}",
        )

    # Check for disallowed characters in arguments
    _validate_no_metacharacters(command)


def _validate_zfs(command: list[str]) -> None:
    """Validate ZFS command against allowlists."""
    if not command:
        raise HTTPException(status_code=400, detail="Empty command")

    # Check command binary allowlist
    if command[0] not in ALLOWED_ZFS_COMMANDS:
        raise HTTPException(
            status_code=403,
            detail=f"Command '{command[0]}' not in command allowlist. Allowed: {sorted(ALLOWED_ZFS_COMMANDS)}",
        )

    # Require a subcommand — bare "zfs" or "zpool" is never valid
    if len(command) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"Missing subcommand for {command[0]}",
        )

    # Check subcommand allowlist
    allowed_subs = ALLOWED_ZFS_SUBCOMMANDS.get(command[0], set())
    if command[1] not in allowed_subs:
        raise HTTPException(
            status_code=403,
            detail=f"Subcommand '{command[1]}' not allowed for {command[0]}. Allowed: {sorted(allowed_subs)}",
        )

    # zfs destroy: exactly 3 elements (zfs, destroy, snapshot@name)
    if command[0] == "zfs" and command[1] == "destroy":
        if len(command) != 3:
            raise HTTPException(
                status_code=403,
                detail="zfs destroy requires exactly one argument (the snapshot)",
            )
        if "@" not in command[2]:
            raise HTTPException(
                status_code=403,
                detail="zfs destroy only allowed on snapshots (target must contain @)",
            )

    # Check for shell metacharacters
    _validate_no_metacharacters(command)


# --- Audit helper ---


async def _audit_backup(action: str, actor: str, details: dict) -> None:
    """Write backup operation to audit log."""
    import json
    from datetime import UTC, datetime

    try:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO ops_audit_log
                   (timestamp, actor, action, resource, result, details)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(UTC).isoformat(),
                    actor,
                    action,
                    "backup",
                    details.get("result", "attempted"),
                    json.dumps(details),
                ),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception:
        logger.exception("Failed to audit backup operation")


# --- Endpoints ---


@router.post("/exec", response_model=BackupResponse)
async def backup_exec(req: ExecRequest, request: Request):
    """Execute a command in a container.

    Restricted to allowed commands in allowed containers only.
    Every call is audit-logged.
    """
    actor = "anonymous"
    if hasattr(request.state, "auth"):
        # auth.identity is a property that returns key_name
        actor = request.state.auth.identity

    # Validate against allowlists; audit rejection if validation fails
    try:
        _validate_exec(req.container, req.command)
    except HTTPException as exc:
        await _audit_backup(
            "backup.exec",
            actor,
            {
                "container": req.container,
                "command": req.command,
                "result": "rejected",
                "reason": exc.detail,
            },
        )
        raise

    # Audit the validated attempt
    await _audit_backup(
        "backup.exec",
        actor,
        {
            "container": req.container,
            "command": req.command,
            "result": "validated",
        },
    )

    # Actual Docker execution would go here.
    # For now, return a placeholder indicating the command was validated.
    # The Docker integration will be added when container connectivity is available.
    return BackupResponse(
        status="validated",
        message=f"Command validated: {req.command[0]} on {req.container}. Docker execution not yet connected.",
    )


@router.post("/zfs", response_model=BackupResponse)
async def backup_zfs(req: ZfsRequest, request: Request):
    """Execute a ZFS command via privileged container.

    Restricted to ZFS/zpool commands with validated subcommands.
    Every call is audit-logged.
    """
    actor = "anonymous"
    if hasattr(request.state, "auth"):
        # auth.identity is a property that returns key_name
        actor = request.state.auth.identity

    # Validate against allowlists; audit rejection if validation fails
    try:
        _validate_zfs(req.command)
    except HTTPException as exc:
        await _audit_backup(
            "backup.zfs",
            actor,
            {
                "command": req.command,
                "result": "rejected",
                "reason": exc.detail,
            },
        )
        raise

    # Audit the validated attempt
    await _audit_backup(
        "backup.zfs",
        actor,
        {
            "command": req.command,
            "result": "validated",
        },
    )

    # Actual privileged container execution would go here.
    return BackupResponse(
        status="validated",
        message=f"Command validated: {' '.join(req.command)}. Privileged execution not yet connected.",
    )
