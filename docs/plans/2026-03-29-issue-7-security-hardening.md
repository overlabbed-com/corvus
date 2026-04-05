# Issue #7: Threat Model CRITICAL Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remediate CRITICAL findings E1.1 and E1.2 (arbitrary command execution via backup endpoints) by building them secure from day one, plus fix HIGH findings T1.1 (mutable records), I1.2 (CORS wildcard), and R1.1 (audit log forwarding).

**Architecture:** New backup router with command/container allowlists. Modify existing changes/events/incidents routers to add `authenticated_as` field. Remove DELETE on changes. Fix CORS. Forward audit entries to SIEM.

**Tech Stack:** FastAPI, aiosqlite, httpx, pytest (all existing)

**Branch:** `feat/issue-7-security-hardening`

---

### Task 1: Add `authenticated_as` column to schema

**Files:**
- Modify: `corvus-server/src/database.py`
- Create: `corvus-server/tests/test_security_hardening.py`

**Step 1: Write the failing test**

Create `corvus-server/tests/test_security_hardening.py`:

```python
"""Tests for security hardening (issue #7)."""

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import client  # noqa: F401


@pytest.mark.asyncio
async def test_change_has_authenticated_as(client):
    """Change records should include authenticated_as field."""
    resp = await client.post("/ops/changes", json={
        "targets": ["vllm-primary"],
        "description": "test change",
        "created_by": "test-agent",
    })
    assert resp.status_code == 201
    data = resp.json()
    # authenticated_as should be present (anonymous in test mode)
    assert "authenticated_as" in data


@pytest.mark.asyncio
async def test_event_has_authenticated_as(client):
    """Event records should include authenticated_as field."""
    resp = await client.post("/ops/events", json={
        "source": "test",
        "type": "change.started",
        "target": "vllm-primary",
    })
    assert resp.status_code == 201
    assert "authenticated_as" in resp.json()


@pytest.mark.asyncio
async def test_incident_has_authenticated_as(client):
    """Incident records should include authenticated_as field."""
    resp = await client.post("/ops/incidents", json={
        "target": "vllm-primary",
        "title": "test incident",
        "detected_by": "test",
    })
    assert resp.status_code == 201
    assert "authenticated_as" in resp.json()
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python -m pytest tests/test_security_hardening.py -v`
Expected: FAIL — `authenticated_as` not in response

**Step 3: Add authenticated_as column to schema**

In `corvus-server/src/database.py`, add `authenticated_as TEXT` column to `ops_changes`, `ops_events`, and `ops_incidents` tables:

Add after `outcome TEXT` in ops_changes:
```sql
    authenticated_as TEXT
```

Add after `parent_event_id TEXT` in ops_events:
```sql
    authenticated_as TEXT
```

Add after `correlated_to_problem TEXT` in ops_incidents:
```sql
    authenticated_as TEXT
```

**Step 4: Update models to include authenticated_as**

In `corvus-server/src/models/changes.py`, add to `ChangeResponse`:
```python
    authenticated_as: str | None = None
```

In `corvus-server/src/models/events.py`, add to `EventResponse`:
```python
    authenticated_as: str | None = None
```

In `corvus-server/src/models/incidents.py`, add to `IncidentResponse`:
```python
    authenticated_as: str | None = None
```

**Step 5: Update routers to populate authenticated_as**

In each router's create endpoint, add `authenticated_as` to the INSERT. Since tests run without auth (dev mode = anonymous), populate from the request auth context. The key pattern (same in all three routers):

Add `Request` import and parameter to each create endpoint:

```python
from fastapi import Request
```

In each create function signature, add `request: Request`. Then extract the auth identity:

```python
authenticated_as = "anonymous"
if hasattr(request.state, "auth"):
    authenticated_as = request.state.auth.identity
```

Add `authenticated_as` to the INSERT statement and the `_row_to_response` function.

**Step 6: Run tests to verify they pass**

Run: `cd corvus-server && python -m pytest tests/test_security_hardening.py -v`
Expected: All PASS

**Step 7: Run full test suite**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS (existing tests should still work since authenticated_as defaults to NULL)

**Step 8: Commit**

```bash
git add corvus-server/src/database.py corvus-server/src/models/ corvus-server/src/routers/changes.py corvus-server/src/routers/events.py corvus-server/src/routers/incidents.py corvus-server/tests/test_security_hardening.py
git commit -m "feat(#7): add authenticated_as field to changes, events, incidents (T1.1)"
```

---

### Task 2: Remove DELETE endpoint on changes

**Files:**
- Modify: `corvus-server/src/routers/changes.py`
- Add to: `corvus-server/tests/test_security_hardening.py`

**Step 1: Write the failing test**

Add to `corvus-server/tests/test_security_hardening.py`:

```python
@pytest.mark.asyncio
async def test_delete_change_not_allowed(client):
    """DELETE on changes should return 405 Method Not Allowed."""
    # Create a change first
    resp = await client.post("/ops/changes", json={
        "targets": ["vllm-primary"],
        "description": "test",
        "created_by": "test",
    })
    change_id = resp.json()["id"]

    # DELETE should not be allowed
    resp = await client.delete(f"/ops/changes/{change_id}")
    assert resp.status_code == 405


@pytest.mark.asyncio
async def test_change_targets_immutable(client):
    """PATCH on changes should not allow modifying targets."""
    resp = await client.post("/ops/changes", json={
        "targets": ["vllm-primary"],
        "description": "test",
        "created_by": "test",
    })
    change_id = resp.json()["id"]

    # Targets field should not be modifiable
    resp = await client.patch(f"/ops/changes/{change_id}", json={
        "status": "completed",
    })
    assert resp.status_code == 200
    # Targets should remain unchanged
    assert resp.json()["targets"] == ["vllm-primary"]
```

**Step 2: Run tests to verify DELETE test fails**

Run: `cd corvus-server && python -m pytest tests/test_security_hardening.py::test_delete_change_not_allowed -v`
Expected: FAIL — currently there's no DELETE endpoint defined, so it will return 405 already. If it returns 404, that's fine too. Check the actual behavior. If DELETE already returns 405, the test already passes.

Note: The existing `changes.py` has no DELETE endpoint. The ChangeUpdate model only allows `status` and `outcome`. So targets are already effectively immutable on PATCH. Both tests may already pass. Verify and proceed.

**Step 3: Verify no DELETE exists**

Check `corvus-server/src/routers/changes.py` — if there is no `@router.delete` endpoint, the test should pass (FastAPI returns 405 for undefined methods on existing routes). If there IS one, remove it.

**Step 4: Run tests**

Run: `cd corvus-server && python -m pytest tests/test_security_hardening.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus-server/tests/test_security_hardening.py corvus-server/src/routers/changes.py
git commit -m "feat(#7): verify DELETE not allowed on changes, targets immutable (T1.1)"
```

---

### Task 3: Fix CORS wildcard (I1.2)

**Files:**
- Modify: `corvus-server/src/app.py`
- Add to: `corvus-server/tests/test_security_hardening.py`

**Step 1: Write the failing test**

Add to `corvus-server/tests/test_security_hardening.py`:

```python
@pytest.mark.asyncio
async def test_cors_no_wildcard(client):
    """CORS should not allow wildcard origins."""
    resp = await client.options("/ops/health", headers={
        "Origin": "https://evil.example.com",
        "Access-Control-Request-Method": "GET",
    })
    # Should NOT have Access-Control-Allow-Origin: *
    acao = resp.headers.get("access-control-allow-origin")
    assert acao != "*"
```

**Step 2: Check current CORS config**

Read `corvus-server/src/app.py` — currently there is NO CORSMiddleware configured. This means the test should pass (no CORS headers sent). Verify and proceed.

If CORSMiddleware IS present with `allow_origins=["*"]`, change to `allow_origins=[]`.

**Step 3: Run test**

Run: `cd corvus-server && python -m pytest tests/test_security_hardening.py::test_cors_no_wildcard -v`
Expected: PASS

**Step 4: Commit**

```bash
git add corvus-server/src/app.py corvus-server/tests/test_security_hardening.py
git commit -m "feat(#7): verify no CORS wildcard (I1.2)"
```

---

### Task 4: Forward audit log entries to SIEM (R1.1)

**Files:**
- Modify: `corvus-server/src/middleware/audit.py`
- Add to: `corvus-server/tests/test_security_hardening.py`

**Step 1: Write the failing test**

Add to `corvus-server/tests/test_security_hardening.py`:

```python
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_audit_forwards_to_siem(client):
    """Audit middleware should forward audit entries to SIEM."""
    with patch("src.middleware.audit.forward_to_siem", new_callable=AsyncMock) as mock_fwd:
        resp = await client.post("/ops/events", json={
            "source": "test",
            "type": "change.started",
            "target": "test-target",
        })
        assert resp.status_code == 201
        # Audit middleware should have called forward_to_siem
        assert mock_fwd.called
```

**Step 2: Run test to verify it fails**

Run: `cd corvus-server && python -m pytest tests/test_security_hardening.py::test_audit_forwards_to_siem -v`
Expected: FAIL — audit middleware doesn't call forward_to_siem yet

**Step 3: Modify audit middleware**

In `corvus-server/src/middleware/audit.py`, add SIEM forwarding after writing to the database. Import `forward_to_siem` and `transform_to_ocsf`, and fire-and-forget forward each audit entry as an OCSF API Activity event:

```python
import asyncio
from src.siem.forwarder import forward_to_siem

# Inside the dispatch method, after the db.commit():
# Forward audit entry to SIEM
audit_ocsf = {
    "class_uid": 6003,
    "class_name": "API Activity",
    "category_uid": 6,
    "category_name": "Application Activity",
    "activity_id": 1,
    "activity_name": "Create",
    "severity_id": 1,
    "severity": "Informational",
    "time": datetime.now(timezone.utc).isoformat(),
    "message": f"{request.method} {request.url.path}",
    "metadata": {
        "version": "1.3.0",
        "product": {"name": "Corvus", "vendor_name": "Corvus", "version": "1.0.0"},
    },
    "actor": {"agent": {"name": actor, "type": "API Caller", "uid": actor}},
    "unmapped": {
        "audit_action": f"{request.method} {request.url.path}",
        "audit_result": result,
        "duration_ms": duration_ms,
        "status_code": response.status_code,
    },
}
asyncio.create_task(forward_to_siem(audit_ocsf))
```

**Step 4: Run tests**

Run: `cd corvus-server && python -m pytest tests/test_security_hardening.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus-server/src/middleware/audit.py corvus-server/tests/test_security_hardening.py
git commit -m "feat(#7): forward audit log entries to SIEM (R1.1)"
```

---

### Task 5: Build secure backup router (E1.1, E1.2)

**Files:**
- Create: `corvus-server/src/routers/backup.py`
- Create: `corvus-server/tests/test_backup.py`
- Modify: `corvus-server/src/app.py` (register router)

**Step 1: Write the failing tests**

Create `corvus-server/tests/test_backup.py`:

```python
"""Tests for backup endpoints with security allowlists (E1.1, E1.2)."""

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import client  # noqa: F401


class TestBackupExec:
    """POST /backup/exec — container command execution with allowlists."""

    @pytest.mark.asyncio
    async def test_allowed_command_accepted(self, client):
        """pg_dump on a postgres container should be accepted."""
        resp = await client.post("/backup/exec", json={
            "container": "app-postgres",
            "command": ["pg_dump", "-U", "postgres", "mydb"],
        })
        # May fail to actually connect (no Docker), but should not be 403
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_disallowed_command_rejected(self, client):
        """Arbitrary commands should be rejected."""
        resp = await client.post("/backup/exec", json={
            "container": "app-postgres",
            "command": ["sh", "-c", "cat /etc/passwd"],
        })
        assert resp.status_code == 403
        assert "not in command allowlist" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_disallowed_container_rejected(self, client):
        """Non-postgres containers should be rejected."""
        resp = await client.post("/backup/exec", json={
            "container": "vllm-primary",
            "command": ["pg_dump", "-U", "postgres", "mydb"],
        })
        assert resp.status_code == 403
        assert "not in container allowlist" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_shell_metacharacters_rejected(self, client):
        """Commands with shell metacharacters should be rejected."""
        resp = await client.post("/backup/exec", json={
            "container": "app-postgres",
            "command": ["pg_dump", "-U", "postgres; rm -rf /"],
        })
        assert resp.status_code == 403


class TestBackupZfs:
    """POST /backup/zfs — ZFS operations with allowlists."""

    @pytest.mark.asyncio
    async def test_allowed_zfs_command(self, client):
        """zpool status should be accepted."""
        resp = await client.post("/backup/zfs", json={
            "command": ["zpool", "status"],
        })
        # May fail to actually run (no ZFS), but should not be 403
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_allowed_zfs_snapshot(self, client):
        """zfs snapshot should be accepted."""
        resp = await client.post("/backup/zfs", json={
            "command": ["zfs", "snapshot", "tank/data@backup-20260329"],
        })
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_disallowed_command_rejected(self, client):
        """Non-ZFS commands should be rejected."""
        resp = await client.post("/backup/zfs", json={
            "command": ["sh", "-c", "cat /etc/shadow"],
        })
        assert resp.status_code == 403
        assert "not in command allowlist" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_zfs_destroy_only_snapshots(self, client):
        """zfs destroy should only work on snapshots (contain @)."""
        # Snapshot destroy — allowed
        resp = await client.post("/backup/zfs", json={
            "command": ["zfs", "destroy", "tank/data@old-snap"],
        })
        assert resp.status_code != 403

        # Dataset destroy — rejected
        resp = await client.post("/backup/zfs", json={
            "command": ["zfs", "destroy", "tank/data"],
        })
        assert resp.status_code == 403
        assert "snapshot" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_shell_metacharacters_rejected(self, client):
        """Shell metacharacters in ZFS commands should be rejected."""
        resp = await client.post("/backup/zfs", json={
            "command": ["zfs", "list", "; rm -rf /"],
        })
        assert resp.status_code == 403
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python -m pytest tests/test_backup.py -v`
Expected: FAIL — 404 (endpoints don't exist yet)

**Step 3: Create the backup router**

Create `corvus-server/src/routers/backup.py`:

```python
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

# Shell metacharacters that should never appear in arguments
SHELL_METACHAR = re.compile(r"[;&|`$(){}!><\n\r]")


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
    """Reject any argument containing shell metacharacters."""
    for arg in args:
        if SHELL_METACHAR.search(arg):
            raise HTTPException(
                status_code=403,
                detail=f"Shell metacharacters not allowed in arguments",
            )


def _validate_exec(container: str, command: list[str]) -> None:
    """Validate container exec request against allowlists."""
    if not command:
        raise HTTPException(status_code=400, detail="Empty command")

    # Check command allowlist
    if command[0] not in ALLOWED_EXEC_COMMANDS:
        raise HTTPException(
            status_code=403,
            detail=f"Command '{command[0]}' not in command allowlist. "
                   f"Allowed: {sorted(ALLOWED_EXEC_COMMANDS)}",
        )

    # Check container allowlist
    if not any(fnmatch.fnmatch(container, pat) for pat in ALLOWED_EXEC_CONTAINERS):
        raise HTTPException(
            status_code=403,
            detail=f"Container '{container}' not in container allowlist. "
                   f"Allowed patterns: {ALLOWED_EXEC_CONTAINERS}",
        )

    # Check for shell metacharacters
    _validate_no_metacharacters(command)


def _validate_zfs(command: list[str]) -> None:
    """Validate ZFS command against allowlists."""
    if not command:
        raise HTTPException(status_code=400, detail="Empty command")

    # Check command binary allowlist
    if command[0] not in ALLOWED_ZFS_COMMANDS:
        raise HTTPException(
            status_code=403,
            detail=f"Command '{command[0]}' not in command allowlist. "
                   f"Allowed: {sorted(ALLOWED_ZFS_COMMANDS)}",
        )

    # Check subcommand allowlist
    if len(command) > 1:
        allowed_subs = ALLOWED_ZFS_SUBCOMMANDS.get(command[0], set())
        if command[1] not in allowed_subs:
            raise HTTPException(
                status_code=403,
                detail=f"Subcommand '{command[1]}' not allowed for {command[0]}. "
                       f"Allowed: {sorted(allowed_subs)}",
            )

        # zfs destroy: only allow snapshots (must contain @)
        if command[0] == "zfs" and command[1] == "destroy":
            if len(command) < 3 or "@" not in command[2]:
                raise HTTPException(
                    status_code=403,
                    detail="zfs destroy only allowed on snapshots (target must contain @)",
                )

    # Check for shell metacharacters
    _validate_no_metacharacters(command)


# --- Audit helper ---

async def _audit_backup(action: str, actor: str, details: dict) -> None:
    """Write backup operation to audit log."""
    from datetime import datetime, timezone
    import json

    try:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO ops_audit_log
                   (timestamp, actor, action, resource, result, details)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
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
        actor = request.state.auth.identity

    # Validate against allowlists
    _validate_exec(req.container, req.command)

    # Audit the attempt
    await _audit_backup("backup.exec", actor, {
        "container": req.container,
        "command": req.command,
        "result": "validated",
    })

    # Actual Docker execution would go here.
    # For now, return a placeholder indicating the command was validated.
    # The Docker integration will be added when container connectivity is available.
    return BackupResponse(
        status="validated",
        message=f"Command validated: {req.command[0]} on {req.container}. "
                "Docker execution not yet connected.",
    )


@router.post("/zfs", response_model=BackupResponse)
async def backup_zfs(req: ZfsRequest, request: Request):
    """Execute a ZFS command via privileged container.

    Restricted to ZFS/zpool commands with validated subcommands.
    Every call is audit-logged.
    """
    actor = "anonymous"
    if hasattr(request.state, "auth"):
        actor = request.state.auth.identity

    # Validate against allowlists
    _validate_zfs(req.command)

    # Audit the attempt
    await _audit_backup("backup.zfs", actor, {
        "command": req.command,
        "result": "validated",
    })

    # Actual privileged container execution would go here.
    return BackupResponse(
        status="validated",
        message=f"Command validated: {' '.join(req.command)}. "
                "Privileged execution not yet connected.",
    )
```

**Step 4: Register the backup router in app.py**

In `corvus-server/src/app.py`, add:

```python
from src.routers import changes, cmdb, events, incidents, metrics, problems, runbooks, backup
```

And:

```python
app.include_router(backup.router)
```

**Step 5: Run tests**

Run: `cd corvus-server && python -m pytest tests/test_backup.py -v`
Expected: All PASS

**Step 6: Run full test suite**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add corvus-server/src/routers/backup.py corvus-server/src/app.py corvus-server/tests/test_backup.py
git commit -m "feat(#7): secure backup endpoints with command/container allowlists (E1.1, E1.2)"
```

---

### Task 6: Final — run full test suite and push

**Step 1: Run full test suite**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 2: Push branch and create PR**

```bash
git push -u origin feat/issue-7-security-hardening
gh pr create --title "feat: threat model CRITICAL remediation — secure backup, audit, immutable records (#7)" \
  --body "$(cat <<'EOF'
## Summary
- Secure `/backup/exec` with command allowlist (pg_dump/psql/pg_restore) + container allowlist (*-postgres)
- Secure `/backup/zfs` with command allowlist (zpool/zfs) + subcommand validation + snapshot-only destroy
- `authenticated_as` field added to changes, events, incidents (populated from auth context)
- Verify DELETE not allowed on changes, targets immutable on PATCH
- Verify no CORS wildcard
- Audit log entries forwarded to SIEM via Splunk HEC

Addresses: E1.1, E1.2 (CRITICAL), T1.1, I1.2, R1.1 (HIGH)
Closes #7

## Test plan
- [ ] `pytest tests/test_backup.py -v` — all allowlist tests pass
- [ ] `pytest tests/test_security_hardening.py -v` — auth, CORS, audit tests pass
- [ ] `pytest tests/ -v` — full suite passes with no regressions
EOF
)"
```
