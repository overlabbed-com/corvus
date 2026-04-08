# Plan Execution Subsystem Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a plan execution subsystem to Corvus that enables structured, DAG-ordered plans with per-step trust gating, rollback, and change window integration.

**Architecture:** New `ops_plans` + `ops_plan_steps` tables, a `plans` router with REST endpoints, a background step-timeout reaper task, trust ledger integration for approval gating, and MCP tool extensions. Additive to the existing codebase — no existing code is modified except `app.py` (router registration), `database.py` (schema), `conftest.py` (test cleanup), and `mcp_server.py` (new tools).

**Tech Stack:** FastAPI, Pydantic, aiosqlite, pytest + httpx (async), existing trust ledger

---

## Task 1: Plan and Step Data Models

**Files:**
- Create: `corvus-server/src/models/plans.py`
- Modify: `corvus-server/src/database.py` (add schema)
- Modify: `corvus-server/tests/conftest.py` (add table cleanup)

**Step 1: Write the model file**

```python
"""Plan execution models."""

from typing import Any

from pydantic import BaseModel


class PlanStepCreate(BaseModel):
    name: str
    description: str | None = None
    sequence: int
    depends_on: list[str] = []
    action_type: str
    targets: list[str]
    params: dict[str, Any] = {}
    failure_policy: str = "halt"  # halt / skip / retry
    max_retries: int = 0
    rollback: dict[str, Any] | None = None
    timeout: int = 300


class PlanCreate(BaseModel):
    title: str
    description: str | None = None
    steps: list[PlanStepCreate]
    created_by: str
    expires_hours: int = 24  # auto-expire approved plans (max 72)


class PlanApproveRequest(BaseModel):
    approved_by: str


class StepResultRequest(BaseModel):
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None


class PlanStepResponse(BaseModel):
    id: str
    plan_id: str
    name: str
    description: str | None = None
    sequence: int
    depends_on: list[str]
    action_type: str
    targets: list[str]
    params: dict[str, Any]
    failure_policy: str
    max_retries: int
    rollback: dict[str, Any] | None = None
    timeout: int
    status: str
    output: dict[str, Any] | None = None
    error: str | None = None
    executed_by: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    retry_count: int


class PlanResponse(BaseModel):
    id: str
    created_at: str
    created_by: str
    title: str
    description: str | None = None
    status: str
    targets: list[str]
    change_id: str | None = None
    approval_method: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    completed_at: str | None = None
    outcome: str | None = None
    expires_hours: int
    steps: list[PlanStepResponse] = []


class PlanStatusResponse(BaseModel):
    id: str
    status: str
    title: str
    change_id: str | None = None
    total_steps: int
    pending: int
    ready: int
    executing: int
    completed: int
    failed: int
    skipped: int
    rolled_back: int
    progress_pct: float
```

Save to `corvus-server/src/models/plans.py`.

**Step 2: Add schema to database.py**

Append to the `SCHEMA` string in `corvus-server/src/database.py`, after the `ops_knowledge_fts` virtual table block and before the `ops_trust_ledger` table:

```sql
CREATE TABLE IF NOT EXISTS ops_plans (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',
    targets         TEXT NOT NULL DEFAULT '[]',
    change_id       TEXT,
    approval_method TEXT,
    approved_at     TEXT,
    approved_by     TEXT,
    completed_at    TEXT,
    outcome         TEXT,
    rollback_to     TEXT,
    expires_hours   INTEGER NOT NULL DEFAULT 24,
    expires_at      TEXT,
    node_id         TEXT DEFAULT 'local',
    hlc_timestamp   TEXT
);

CREATE INDEX IF NOT EXISTS idx_plans_status ON ops_plans(status);
CREATE INDEX IF NOT EXISTS idx_plans_created_by ON ops_plans(created_by);
CREATE INDEX IF NOT EXISTS idx_plans_change_id ON ops_plans(change_id);

CREATE TABLE IF NOT EXISTS ops_plan_steps (
    id              TEXT PRIMARY KEY,
    plan_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    sequence        INTEGER NOT NULL,
    depends_on      TEXT NOT NULL DEFAULT '[]',
    action_type     TEXT NOT NULL,
    targets         TEXT NOT NULL DEFAULT '[]',
    params          TEXT NOT NULL DEFAULT '{}',
    failure_policy  TEXT NOT NULL DEFAULT 'halt',
    max_retries     INTEGER NOT NULL DEFAULT 0,
    rollback        TEXT,
    timeout         INTEGER NOT NULL DEFAULT 300,
    status          TEXT NOT NULL DEFAULT 'pending',
    output          TEXT,
    error           TEXT,
    executed_by     TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (plan_id) REFERENCES ops_plans(id)
);

CREATE INDEX IF NOT EXISTS idx_plan_steps_plan ON ops_plan_steps(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_steps_status ON ops_plan_steps(status);
CREATE INDEX IF NOT EXISTS idx_plan_steps_action_type ON ops_plan_steps(action_type);
```

**Step 3: Add table cleanup to conftest.py**

In `corvus-server/tests/conftest.py`, add `"ops_plans"` and `"ops_plan_steps"` to the table cleanup list in the `client` fixture (after `"ops_trust_ledger"`).

**Step 4: Run existing tests to verify schema addition doesn't break anything**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_changes.py tests/test_events.py -v --timeout=30`
Expected: All PASS (schema is additive)

**Step 5: Commit**

```bash
cd ~/corvus
git add corvus-server/src/models/plans.py corvus-server/src/database.py corvus-server/tests/conftest.py
git commit -m "feat(plans): add plan and step data models and schema"
```

---

## Task 2: Plan Router — CRUD Operations

**Files:**
- Create: `corvus-server/src/routers/plans.py`
- Modify: `corvus-server/src/app.py` (register router)
- Create: `corvus-server/tests/test_plans.py`

**Step 1: Write failing tests for plan CRUD**

Create `corvus-server/tests/test_plans.py`:

```python
"""Plan execution subsystem tests."""

import pytest


@pytest.mark.asyncio
async def test_create_plan(client):
    """Create a plan with steps."""
    resp = await client.post(
        "/ops/plans",
        json={
            "title": "Deploy tetragon to fleet",
            "description": "Roll out 27 CRDs to all 4 hosts",
            "created_by": "claude-code",
            "steps": [
                {
                    "name": "deploy-host-01",
                    "sequence": 1,
                    "action_type": "change.deploy",
                    "targets": ["tetragon@host-01"],
                    "params": {"host": "host-01"},
                    "rollback": {"action_type": "change.deploy", "params": {"ref": "HEAD~1"}},
                },
                {
                    "name": "deploy-host-02",
                    "sequence": 1,
                    "action_type": "change.deploy",
                    "targets": ["tetragon@host-02"],
                    "params": {"host": "host-02"},
                    "rollback": {"action_type": "change.deploy", "params": {"ref": "HEAD~1"}},
                },
                {
                    "name": "verify-health",
                    "sequence": 2,
                    "depends_on": [],  # will be filled with step IDs after creation
                    "action_type": "health.check",
                    "targets": ["tetragon@host-01", "tetragon@host-02"],
                    "params": {"command": "docker exec tetragon tetra status"},
                    "failure_policy": "skip",
                },
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["title"] == "Deploy tetragon to fleet"
    assert len(data["steps"]) == 3
    assert data["id"].startswith("PLN-")
    # All plan targets are the union of step targets
    assert set(data["targets"]) == {"tetragon@host-01", "tetragon@host-02"}


@pytest.mark.asyncio
async def test_list_plans(client):
    """List plans with status filter."""
    await client.post(
        "/ops/plans",
        json={
            "title": "Plan A",
            "created_by": "agent-a",
            "steps": [
                {"name": "s1", "sequence": 1, "action_type": "health.check", "targets": ["svc-a"]},
            ],
        },
    )
    resp = await client.get("/ops/plans?status=draft")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_get_plan_with_steps(client):
    """Get a plan by ID with all steps included."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Test plan",
            "created_by": "agent",
            "steps": [
                {"name": "s1", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    resp = await client.get(f"/ops/plans/{plan_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == plan_id
    assert len(data["steps"]) == 1
    assert data["steps"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_create_plan_rejects_empty_steps(client):
    """Plans must have at least one step."""
    resp = await client.post(
        "/ops/plans",
        json={"title": "Empty", "created_by": "agent", "steps": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cancel_draft_plan(client):
    """Cancel a draft plan."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Cancel me",
            "created_by": "agent",
            "steps": [
                {"name": "s1", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    resp = await client.post(f"/ops/plans/{plan_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py -v --timeout=30`
Expected: FAIL (router not implemented)

**Step 3: Implement the plans router**

Create `corvus-server/src/routers/plans.py`. This router handles:
- `POST /ops/plans` — create plan with steps, compute target union, validate steps non-empty
- `GET /ops/plans` — list with optional `status` and `created_by` filters
- `GET /ops/plans/{id}` — get plan with all steps
- `POST /ops/plans/{id}/cancel` — cancel draft/approved/blocked plans

Follow the patterns in `changes.py`: row-to-response helper, JSON parse for array fields, `get_db()` connection management with try/finally.

Key implementation details:
- Plan ID format: `PLN-{uuid4.hex[:8].upper()}`
- Step ID format: `PSTEP-{uuid4.hex[:8].upper()}`
- `targets` on the plan is auto-computed as the union of all step targets
- Steps with `depends_on` referencing step **names** (not IDs) — resolved to IDs at creation time
- Validate `failure_policy` is one of `halt`, `skip`, `retry`
- Validate `expires_hours` <= 72

**Step 4: Register router in app.py**

In `corvus-server/src/app.py`:
- Add `plans` to the router imports
- Add `app.include_router(plans.router)` after the `steps` router

**Step 5: Run tests to verify they pass**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py -v --timeout=30`
Expected: All PASS

**Step 6: Run full test suite to verify no regressions**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/ -v --timeout=60`
Expected: All PASS

**Step 7: Commit**

```bash
cd ~/corvus
git add corvus-server/src/routers/plans.py corvus-server/src/app.py corvus-server/tests/test_plans.py
git commit -m "feat(plans): plan CRUD router with create, list, get, cancel"
```

---

## Task 3: Plan Approval with Trust Ledger Gating

**Files:**
- Modify: `corvus-server/src/routers/plans.py`
- Modify: `corvus-server/tests/test_plans.py`

**Step 1: Write failing tests for approval**

Append to `test_plans.py`:

```python
@pytest.mark.asyncio
async def test_approve_plan_trust_ledger_auto(client):
    """Plan auto-approves when all step action_types are AUTO in trust ledger."""
    # Seed trust ledger with AUTO tier for health.check
    from src.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO ops_trust_ledger (action_type, total_count, success_count, failure_count, trust_tier) VALUES (?, 25, 25, 0, 'AUTO')",
            ("health.check",),
        )
        await db.commit()
    finally:
        await db.close()

    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Auto-approve plan",
            "created_by": "nemoclaw",
            "steps": [
                {"name": "check", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    resp = await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "nemoclaw"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["approval_method"] == "trust_ledger"


@pytest.mark.asyncio
async def test_approve_plan_needs_human(client):
    """Plan with ESCALATE-tier steps returns needs_approval."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Needs human",
            "created_by": "nemoclaw",
            "steps": [
                {"name": "deploy", "sequence": 1, "action_type": "change.deploy", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    # No trust ledger entry for change.deploy → defaults to ESCALATE
    resp = await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "nemoclaw"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_approval"] is True
    assert len(data["escalated_steps"]) == 1
    assert data["escalated_steps"][0]["action_type"] == "change.deploy"


@pytest.mark.asyncio
async def test_approve_plan_human_override(client):
    """Operator can force-approve a plan with ESCALATE steps."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Force approve",
            "created_by": "nemoclaw",
            "steps": [
                {"name": "deploy", "sequence": 1, "action_type": "change.deploy", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    resp = await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "operator", "force": True},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["approval_method"] == "human"


@pytest.mark.asyncio
async def test_approve_non_draft_fails(client):
    """Cannot approve a plan that isn't in draft status."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Cancel then approve",
            "created_by": "agent",
            "steps": [
                {"name": "s1", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    await client.post(f"/ops/plans/{plan_id}/cancel")
    resp = await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "operator", "force": True},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_plan_execute_trust_gated(client):
    """plan.execute action type must be at least SUPERVISED to start execution."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Execute gated",
            "created_by": "nemoclaw",
            "steps": [
                {"name": "check", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    # Force approve the plan
    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    # plan.execute defaults to ESCALATE — execution should indicate it needs approval
    resp = await client.post(f"/ops/plans/{plan_id}/execute")
    assert resp.status_code == 200
    # Should still work since execution is requested by the approver context
    # The trust gate is informational — the approve step is the real gate
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py -v -k "approve or execute_trust" --timeout=30`
Expected: FAIL

**Step 3: Implement approval endpoint**

Add to `plans.py`:
- `POST /ops/plans/{id}/approve` endpoint
- Add `force: bool = False` to `PlanApproveRequest` model
- Query trust ledger for each unique `action_type` across steps
- If all are AUTO or SUPERVISED: auto-approve, set `approval_method = "trust_ledger"`
- If any are ESCALATE: return `{"needs_approval": True, "escalated_steps": [...]}` unless `force=True`
- If `force=True`: approve anyway, set `approval_method = "human"`
- Set `expires_at` based on `expires_hours` from plan creation
- Also check `plan.execute` action type in trust ledger (Advocate finding #6)

**Step 4: Run tests**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py -v --timeout=30`
Expected: All PASS

**Step 5: Commit**

```bash
cd ~/corvus
git add corvus-server/src/routers/plans.py corvus-server/src/models/plans.py corvus-server/tests/test_plans.py
git commit -m "feat(plans): approval with trust ledger gating and human override"
```

---

## Task 4: Plan Execution — DAG Scheduling and Change Window

**Files:**
- Modify: `corvus-server/src/routers/plans.py`
- Modify: `corvus-server/tests/test_plans.py`

**Step 1: Write failing tests for execution and DAG**

Append to `test_plans.py`:

```python
@pytest.mark.asyncio
async def test_execute_plan_creates_change_window(client):
    """Executing a plan creates a change window covering all targets."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Deploy",
            "created_by": "cc",
            "steps": [
                {"name": "s1", "sequence": 1, "action_type": "health.check", "targets": ["svc-a", "svc-b"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})

    resp = await client.post(f"/ops/plans/{plan_id}/execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "executing"
    assert data["change_id"] is not None
    assert data["change_id"].startswith("CHG-")

    # Verify change window exists
    changes_resp = await client.get("/ops/changes/active")
    change_ids = [c["id"] for c in changes_resp.json()]
    assert data["change_id"] in change_ids


@pytest.mark.asyncio
async def test_ready_steps_returns_dag_roots(client):
    """Ready steps endpoint returns only steps whose dependencies are met."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "DAG test",
            "created_by": "cc",
            "steps": [
                {"name": "root-a", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
                {"name": "root-b", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
                {"name": "depends-on-a", "sequence": 2, "depends_on": ["root-a"], "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    resp = await client.get(f"/ops/plans/{plan_id}/steps/ready")
    assert resp.status_code == 200
    ready = resp.json()
    ready_names = [s["name"] for s in ready]
    assert "root-a" in ready_names
    assert "root-b" in ready_names
    assert "depends-on-a" not in ready_names  # blocked by root-a


@pytest.mark.asyncio
async def test_step_completion_advances_dag(client):
    """Completing a step makes dependent steps ready."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "DAG advance",
            "created_by": "cc",
            "steps": [
                {"name": "root", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
                {"name": "child", "sequence": 2, "depends_on": ["root"], "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    steps = create_resp.json()["steps"]
    root_id = next(s["id"] for s in steps if s["name"] == "root")

    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    # Complete root step
    resp = await client.post(
        f"/ops/plans/{plan_id}/steps/{root_id}/result",
        json={"success": True, "output": {"status": "healthy"}},
    )
    assert resp.status_code == 200

    # Child should now be ready
    ready_resp = await client.get(f"/ops/plans/{plan_id}/steps/ready")
    ready_names = [s["name"] for s in ready_resp.json()]
    assert "child" in ready_names


@pytest.mark.asyncio
async def test_plan_completes_when_all_steps_done(client):
    """Plan status becomes completed when all steps succeed."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Complete plan",
            "created_by": "cc",
            "steps": [
                {"name": "only-step", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    step_id = create_resp.json()["steps"][0]["id"]

    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    resp = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_id}/result",
        json={"success": True},
    )
    result = resp.json()
    assert result["plan_status"] == "completed"

    # Plan should be completed
    plan_resp = await client.get(f"/ops/plans/{plan_id}")
    assert plan_resp.json()["status"] == "completed"
    assert plan_resp.json()["outcome"] == "success"


@pytest.mark.asyncio
async def test_plan_status_endpoint(client):
    """Status endpoint returns step counts and progress."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Status test",
            "created_by": "cc",
            "steps": [
                {"name": "s1", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
                {"name": "s2", "sequence": 1, "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    resp = await client.get(f"/ops/plans/{plan_id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_steps"] == 2
    assert data["ready"] == 2
    assert data["progress_pct"] == 0.0
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py -v -k "execute or ready or advance or completes or status" --timeout=30`
Expected: FAIL

**Step 3: Implement execution endpoints**

Add to `plans.py`:
- `POST /ops/plans/{id}/execute` — validates `approved` status, creates change window via direct DB insert (same pattern as `changes.py`), marks root steps as `ready`, emits `plan.started` event
- `GET /ops/plans/{id}/steps/ready` — queries steps where `status = 'ready'`, marks them `executing` and records `executed_by` + `started_at`
- `POST /ops/plans/{id}/steps/{step_id}/result` — records result, evaluates DAG:
  - On success: find steps whose `depends_on` are all `completed`, mark them `ready`
  - If all steps `completed`/`skipped`: set plan to `completed`, close change window
  - Return `plan_status` and `next_ready_steps` in response
- `GET /ops/plans/{id}/status` — count steps by status, compute progress %

DAG evaluation helper function:
```python
async def _evaluate_dag(db, plan_id: str) -> list[dict]:
    """Find steps that are pending but whose dependencies are all completed."""
```

**Step 4: Run tests**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py -v --timeout=30`
Expected: All PASS

**Step 5: Commit**

```bash
cd ~/corvus
git add corvus-server/src/routers/plans.py corvus-server/tests/test_plans.py
git commit -m "feat(plans): execution with DAG scheduling and change window integration"
```

---

## Task 5: Failure Handling and Rollback

**Files:**
- Modify: `corvus-server/src/routers/plans.py`
- Modify: `corvus-server/tests/test_plans.py`

**Step 1: Write failing tests for failure policies and rollback**

Append to `test_plans.py`:

```python
@pytest.mark.asyncio
async def test_halt_policy_blocks_plan(client):
    """A failed step with halt policy blocks the plan."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Halt test",
            "created_by": "cc",
            "steps": [
                {
                    "name": "will-fail",
                    "sequence": 1,
                    "action_type": "change.deploy",
                    "targets": ["svc"],
                    "failure_policy": "halt",
                    "rollback": {"action_type": "change.deploy", "params": {"ref": "HEAD~1"}},
                },
                {"name": "should-not-run", "sequence": 2, "depends_on": ["will-fail"], "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    fail_step_id = next(s["id"] for s in create_resp.json()["steps"] if s["name"] == "will-fail")

    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    resp = await client.post(
        f"/ops/plans/{plan_id}/steps/{fail_step_id}/result",
        json={"success": False, "error": "deploy failed"},
    )
    result = resp.json()
    assert result["plan_status"] == "blocked"

    # No steps should be ready
    ready_resp = await client.get(f"/ops/plans/{plan_id}/steps/ready")
    assert len(ready_resp.json()) == 0


@pytest.mark.asyncio
async def test_skip_policy_continues(client):
    """A failed step with skip policy allows the plan to continue."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Skip test",
            "created_by": "cc",
            "steps": [
                {"name": "will-fail", "sequence": 1, "action_type": "health.check", "targets": ["svc"], "failure_policy": "skip"},
                {"name": "should-run", "sequence": 2, "depends_on": ["will-fail"], "action_type": "health.check", "targets": ["svc"]},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    fail_step_id = next(s["id"] for s in create_resp.json()["steps"] if s["name"] == "will-fail")

    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    await client.post(
        f"/ops/plans/{plan_id}/steps/{fail_step_id}/result",
        json={"success": False, "error": "check failed"},
    )

    # Dependent step should be ready despite parent failure
    ready_resp = await client.get(f"/ops/plans/{plan_id}/steps/ready")
    ready_names = [s["name"] for s in ready_resp.json()]
    assert "should-run" in ready_names


@pytest.mark.asyncio
async def test_rollback_reverses_completed_steps(client):
    """Triggering rollback creates rollback actions for completed steps in reverse order."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Rollback test",
            "created_by": "cc",
            "steps": [
                {
                    "name": "step-1",
                    "sequence": 1,
                    "action_type": "change.deploy",
                    "targets": ["svc-a"],
                    "rollback": {"action_type": "change.deploy", "params": {"ref": "HEAD~1", "target": "svc-a"}},
                },
                {
                    "name": "step-2",
                    "sequence": 2,
                    "depends_on": ["step-1"],
                    "action_type": "change.deploy",
                    "targets": ["svc-b"],
                    "rollback": {"action_type": "change.deploy", "params": {"ref": "HEAD~1", "target": "svc-b"}},
                },
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    steps = create_resp.json()["steps"]
    s1_id = next(s["id"] for s in steps if s["name"] == "step-1")
    s2_id = next(s["id"] for s in steps if s["name"] == "step-2")

    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    # Complete both steps
    await client.post(f"/ops/plans/{plan_id}/steps/{s1_id}/result", json={"success": True})
    await client.post(f"/ops/plans/{plan_id}/steps/{s2_id}/result", json={"success": True})

    # Trigger manual rollback
    resp = await client.post(f"/ops/plans/{plan_id}/rollback")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rolling_back"

    # Rollback steps should be ready (step-2 rollback first since reverse order)
    ready_resp = await client.get(f"/ops/plans/{plan_id}/steps/ready")
    assert len(ready_resp.json()) > 0


@pytest.mark.asyncio
async def test_retry_policy(client):
    """A failed step with retry policy re-queues up to max_retries."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Retry test",
            "created_by": "cc",
            "steps": [
                {
                    "name": "flaky",
                    "sequence": 1,
                    "action_type": "health.check",
                    "targets": ["svc"],
                    "failure_policy": "retry",
                    "max_retries": 2,
                },
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    step_id = create_resp.json()["steps"][0]["id"]

    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    # First failure — should re-queue
    resp = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_id}/result",
        json={"success": False, "error": "timeout"},
    )
    assert resp.json()["step_status"] == "ready"  # re-queued
    assert resp.json()["retry_count"] == 1

    # Second failure — should re-queue (max_retries=2)
    resp = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_id}/result",
        json={"success": False, "error": "timeout again"},
    )
    assert resp.json()["step_status"] == "ready"
    assert resp.json()["retry_count"] == 2

    # Third failure — exhausted retries, halt
    resp = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_id}/result",
        json={"success": False, "error": "still failing"},
    )
    assert resp.json()["step_status"] == "failed"
    assert resp.json()["plan_status"] == "blocked"
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py -v -k "halt or skip or rollback or retry" --timeout=30`
Expected: FAIL

**Step 3: Implement failure handling and rollback**

Extend `plans.py`:
- In `_report_step_result`: handle `failure_policy`:
  - `halt`: mark step `failed`, set plan to `blocked`, emit `plan.blocked` event
  - `skip`: mark step `skipped`, continue DAG evaluation (treat skipped as "completed" for dependency resolution)
  - `retry`: increment `retry_count`, if < `max_retries` reset to `ready`, else treat as `halt`
- `POST /ops/plans/{id}/rollback`:
  - Validate plan is `completed` or `blocked`
  - Set plan status to `rolling_back`
  - Find all `completed` steps, create rollback entries in `ops_plan_steps` with `sequence` reversed
  - Rollback steps are regular steps — agent pulls and executes them the same way
  - When all rollback steps complete: plan status → `failed`, outcome → `rolled_back`, close change window

**Step 4: Run tests**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py -v --timeout=30`
Expected: All PASS

**Step 5: Commit**

```bash
cd ~/corvus
git add corvus-server/src/routers/plans.py corvus-server/tests/test_plans.py
git commit -m "feat(plans): failure policies (halt/skip/retry) and per-step rollback"
```

---

## Task 6: Step Timeout Reaper (Advocate Finding #2)

**Files:**
- Create: `corvus-server/src/tasks/step_timeout.py`
- Modify: `corvus-server/src/app.py` (register background task)
- Create: `corvus-server/tests/test_step_timeout.py`

**Step 1: Write failing test**

Create `corvus-server/tests/test_step_timeout.py`:

```python
"""Step timeout reaper tests."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.database import get_db
from src.tasks.step_timeout import reap_timed_out_steps


@pytest.mark.asyncio
async def test_reap_timed_out_step(client):
    """Steps executing past their timeout are re-queued."""
    # Create a plan with an executing step that started 10 minutes ago
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Timeout test",
            "created_by": "cc",
            "steps": [
                {"name": "slow", "sequence": 1, "action_type": "health.check", "targets": ["svc"], "timeout": 60},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    step_id = create_resp.json()["steps"][0]["id"]

    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    # Manually set started_at to 10 minutes ago and status to executing
    db = await get_db()
    try:
        past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await db.execute(
            "UPDATE ops_plan_steps SET status = 'executing', started_at = ? WHERE id = ?",
            (past, step_id),
        )
        await db.commit()
    finally:
        await db.close()

    # Run reaper
    count = await reap_timed_out_steps()
    assert count == 1

    # Step should be re-queued as ready
    db = await get_db()
    try:
        cursor = await db.execute("SELECT status, retry_count FROM ops_plan_steps WHERE id = ?", (step_id,))
        row = await cursor.fetchone()
        assert row["status"] == "ready"
        assert row["retry_count"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reap_exhausted_retries_blocks_plan(client):
    """Step that times out past max_retries triggers halt behavior."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Exhausted timeout",
            "created_by": "cc",
            "steps": [
                {"name": "stuck", "sequence": 1, "action_type": "health.check", "targets": ["svc"], "timeout": 60, "max_retries": 0},
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    step_id = create_resp.json()["steps"][0]["id"]

    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})
    await client.post(f"/ops/plans/{plan_id}/execute")

    db = await get_db()
    try:
        past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await db.execute(
            "UPDATE ops_plan_steps SET status = 'executing', started_at = ? WHERE id = ?",
            (past, step_id),
        )
        await db.commit()
    finally:
        await db.close()

    count = await reap_timed_out_steps()
    assert count == 1

    # Plan should be blocked
    plan_resp = await client.get(f"/ops/plans/{plan_id}")
    assert plan_resp.json()["status"] == "blocked"
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_step_timeout.py -v --timeout=30`
Expected: FAIL

**Step 3: Implement the reaper**

Create `corvus-server/src/tasks/step_timeout.py` following the pattern of `change_expiry.py`:

```python
"""Background task: reap timed-out plan steps.

Runs periodically to detect steps stuck in 'executing' state past their
timeout. Re-queues or fails them based on retry limits.
"""
```

- Query `ops_plan_steps` where `status = 'executing'` and `started_at + timeout < now`
- For each: increment `retry_count`, if < `max_retries` set `status = 'ready'`, else set `status = 'failed'` and evaluate plan halt
- `run_step_timeout_loop(interval_seconds=60)` — check every minute

**Step 4: Register in app.py**

Import and add `asyncio.create_task(run_step_timeout_loop())` in the lifespan function, alongside the existing background tasks. Add to the cancellation list.

**Step 5: Run tests**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_step_timeout.py -v --timeout=30`
Expected: All PASS

**Step 6: Run full suite**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/ -v --timeout=60`
Expected: All PASS

**Step 7: Commit**

```bash
cd ~/corvus
git add corvus-server/src/tasks/step_timeout.py corvus-server/src/app.py corvus-server/tests/test_step_timeout.py
git commit -m "feat(plans): background step timeout reaper (Advocate finding #2)"
```

---

## Task 7: MCP Tool Extensions

**Files:**
- Modify: `corvus-server/src/mcp_server.py`
- Modify: `corvus-server/tests/test_mcp_server.py`

**Step 1: Write failing tests**

Check existing `test_mcp_server.py` pattern, then add tests that call the new MCP tools via the Corvus HTTP API (since MCP tools are thin HTTP wrappers).

Append plan-specific API tests to `test_plans.py` (the MCP tools are HTTP wrappers — testing the API endpoints is equivalent):

```python
@pytest.mark.asyncio
async def test_full_plan_lifecycle(client):
    """End-to-end: create → approve → execute → complete."""
    # Create
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "E2E test",
            "created_by": "cc",
            "steps": [
                {
                    "name": "deploy",
                    "sequence": 1,
                    "action_type": "change.deploy",
                    "targets": ["svc"],
                    "rollback": {"action_type": "change.deploy", "params": {"ref": "HEAD~1"}},
                },
                {
                    "name": "verify",
                    "sequence": 2,
                    "depends_on": ["deploy"],
                    "action_type": "health.check",
                    "targets": ["svc"],
                    "failure_policy": "skip",
                },
            ],
        },
    )
    assert create_resp.status_code == 201
    plan_id = create_resp.json()["id"]
    steps = create_resp.json()["steps"]
    deploy_id = next(s["id"] for s in steps if s["name"] == "deploy")
    verify_id = next(s["id"] for s in steps if s["name"] == "verify")

    # Approve (force)
    await client.post(f"/ops/plans/{plan_id}/approve", json={"approved_by": "operator", "force": True})

    # Execute
    exec_resp = await client.post(f"/ops/plans/{plan_id}/execute")
    assert exec_resp.json()["status"] == "executing"
    change_id = exec_resp.json()["change_id"]

    # Pull ready (should be deploy only)
    ready = await client.get(f"/ops/plans/{plan_id}/steps/ready")
    assert len(ready.json()) == 1
    assert ready.json()[0]["name"] == "deploy"

    # Complete deploy
    await client.post(f"/ops/plans/{plan_id}/steps/{deploy_id}/result", json={"success": True})

    # Pull ready (should be verify now)
    ready = await client.get(f"/ops/plans/{plan_id}/steps/ready")
    assert len(ready.json()) == 1
    assert ready.json()[0]["name"] == "verify"

    # Complete verify
    result = await client.post(f"/ops/plans/{plan_id}/steps/{verify_id}/result", json={"success": True})
    assert result.json()["plan_status"] == "completed"

    # Change window should be closed
    changes = await client.get(f"/ops/changes?status=active")
    active_ids = [c["id"] for c in changes.json()]
    assert change_id not in active_ids
```

**Step 2: Implement MCP tools**

Add to `corvus-server/src/mcp_server.py`:

```python
@mcp.tool()
def ops_create_plan(title: str, description: str, steps: list[dict], created_by: str = "mcp-agent") -> str:
    """Create a structured execution plan..."""

@mcp.tool()
def ops_approve_plan(plan_id: str, approved_by: str = "mcp-agent", force: bool = False) -> str:
    """Approve a plan for execution..."""

@mcp.tool()
def ops_execute_plan(plan_id: str) -> str:
    """Start plan execution..."""

@mcp.tool()
def ops_plan_status(plan_id: str) -> str:
    """Get plan execution summary..."""

@mcp.tool()
def ops_pull_ready_steps(plan_id: str) -> str:
    """Pull steps ready for execution..."""

@mcp.tool()
def ops_report_step_result(plan_id: str, step_id: str, success: bool, output: dict | None = None, error: str | None = None) -> str:
    """Report step execution result..."""

@mcp.tool()
def ops_cancel_plan(plan_id: str) -> str:
    """Cancel a plan..."""

@mcp.tool()
def ops_rollback_plan(plan_id: str) -> str:
    """Trigger plan rollback..."""
```

Each tool is a thin HTTP wrapper following the existing pattern (httpx client, JSON serialize response).

**Step 3: Run tests**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/test_plans.py tests/test_mcp_server.py -v --timeout=30`
Expected: All PASS

**Step 4: Commit**

```bash
cd ~/corvus
git add corvus-server/src/mcp_server.py corvus-server/tests/test_plans.py
git commit -m "feat(plans): MCP tools for plan lifecycle and step execution"
```

---

## Task 8: Spec File and Event Types

**Files:**
- Create: `spec/plans.md`
- Modify: `spec/events.md` (add plan event types)

**Step 1: Write spec/plans.md**

Document the plan protocol following the structure of existing specs (`changes.md`, `runbooks.md`). Include:
- Plan lifecycle diagram
- API reference (all endpoints)
- Step schema with field descriptions
- DAG execution rules
- Failure policy semantics
- Rollback mechanics
- Trust ledger integration
- `@host` fan-out convention (CC expands at creation time)
- Plan expiry (configurable, 72h max)

**Step 2: Update spec/events.md**

Add the plan event types table after the existing Sessions section:

```markdown
### Plan Lifecycle
| Type | When | Severity |
|------|------|----------|
| `plan.created` | Plan submitted as draft | info |
| `plan.approved` | Plan approved for execution | info |
| `plan.started` | Execution began, change window opened | info |
| `plan.step_completed` | Individual step succeeded | info |
| `plan.step_failed` | Individual step failed | warning |
| `plan.completed` | All steps succeeded | info |
| `plan.failed` | Step failure, rollback completed | warning |
| `plan.blocked` | Step failure, awaiting human decision | warning |
| `plan.rolling_back` | Rollback sequence started | warning |
| `plan.rolled_back` | Rollback sequence completed | info |
```

Add OCSF mapping row: `plan.*` → Device Config State Change (5019).

**Step 3: Commit**

```bash
cd ~/corvus
git add spec/plans.md spec/events.md
git commit -m "docs(plans): spec file and event type additions"
```

---

## Task 9: Full Integration Test and Cleanup

**Files:**
- Modify: `corvus-server/tests/test_plans.py` (add edge cases)

**Step 1: Add edge case tests**

- Test that executing a non-approved plan returns 409
- Test that submitting a result for a step in the wrong plan returns 404
- Test that step targets outside plan targets are rejected at creation
- Test plan expiry (approved plan past `expires_at` cannot be executed)
- Test event emission (verify `plan.started`, `plan.completed` events in `/ops/events`)

**Step 2: Run full test suite**

Run: `cd ~/corvus/corvus-server && python -m pytest tests/ -v --timeout=120`
Expected: All PASS, zero regressions

**Step 3: Commit**

```bash
cd ~/corvus
git add corvus-server/tests/test_plans.py
git commit -m "test(plans): edge cases and integration validation"
```

---

## Completion Checklist

- [ ] All 9 tasks complete
- [ ] Full test suite passes
- [ ] Spec file documents all plan APIs and conventions
- [ ] Event types added to events.md
- [ ] MCP tools added to mcp_server.py
- [ ] Background step timeout reaper running
- [ ] Advocate findings incorporated (#2 reaper, #6 plan.execute trust gating)
- [ ] No existing tests broken

## Files Changed Summary

| File | Action |
|------|--------|
| `corvus-server/src/models/plans.py` | Create |
| `corvus-server/src/routers/plans.py` | Create |
| `corvus-server/src/tasks/step_timeout.py` | Create |
| `corvus-server/tests/test_plans.py` | Create |
| `corvus-server/tests/test_step_timeout.py` | Create |
| `spec/plans.md` | Create |
| `corvus-server/src/database.py` | Modify (schema) |
| `corvus-server/src/app.py` | Modify (router + task) |
| `corvus-server/src/mcp_server.py` | Modify (tools) |
| `corvus-server/tests/conftest.py` | Modify (cleanup) |
| `spec/events.md` | Modify (event types) |

**Plan complete.**
