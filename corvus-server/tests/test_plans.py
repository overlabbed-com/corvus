"""Plan execution subsystem tests."""

import pytest


def _make_plan_payload(**overrides):
    """Helper to build a valid plan creation payload."""
    base = {
        "title": "Deploy model update",
        "description": "Rolling update of vLLM primary",
        "created_by": "claude-code",
        "expires_hours": 24,
        "steps": [
            {
                "name": "pull-image",
                "description": "Pull new vLLM image",
                "sequence": 1,
                "action_type": "docker_pull",
                "targets": ["vllm-primary"],
                "params": {"image": "vllm/vllm-openai:v0.18.1"},
                "failure_policy": "halt",
                "timeout": 120,
            },
            {
                "name": "restart-service",
                "description": "Restart the vLLM container",
                "sequence": 2,
                "depends_on": ["pull-image"],
                "action_type": "docker_restart",
                "targets": ["vllm-primary"],
                "params": {},
                "failure_policy": "halt",
                "timeout": 60,
            },
            {
                "name": "verify-health",
                "description": "Health check after restart",
                "sequence": 3,
                "depends_on": ["restart-service"],
                "action_type": "health_check",
                "targets": ["litellm"],
                "params": {"url": "http://litellm:4000/health"},
                "failure_policy": "skip",
                "timeout": 30,
            },
        ],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_plan(client):
    """Create a plan with steps -- verify targets are unioned, step IDs assigned."""
    payload = _make_plan_payload()
    resp = await client.post("/ops/plans", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    # Plan-level checks
    assert data["id"].startswith("PLN-")
    assert data["status"] == "draft"
    assert data["title"] == "Deploy model update"
    assert data["created_by"] == "claude-code"
    assert data["expires_hours"] == 24

    # Targets should be the union of all step targets
    assert set(data["targets"]) == {"vllm-primary", "litellm"}

    # Steps should all have IDs
    assert len(data["steps"]) == 3
    for step in data["steps"]:
        assert step["id"].startswith("PSTEP-")
        assert step["plan_id"] == data["id"]
        assert step["status"] == "pending"
        assert step["retry_count"] == 0


@pytest.mark.asyncio
async def test_list_plans(client):
    """List plans with status filter."""
    # Create two plans
    await client.post("/ops/plans", json=_make_plan_payload(title="Plan A"))
    await client.post("/ops/plans", json=_make_plan_payload(title="Plan B"))

    # List all
    resp = await client.get("/ops/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2

    # Filter by status
    resp = await client.get("/ops/plans", params={"status": "draft"})
    assert resp.status_code == 200
    assert all(p["status"] == "draft" for p in resp.json())

    # Filter by created_by
    resp = await client.get("/ops/plans", params={"created_by": "claude-code"})
    assert resp.status_code == 200
    assert all(p["created_by"] == "claude-code" for p in resp.json())

    # Filter by non-existent status returns empty
    resp = await client.get("/ops/plans", params={"status": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_plan_with_steps(client):
    """Get a plan by ID with all steps included."""
    create_resp = await client.post("/ops/plans", json=_make_plan_payload())
    plan_id = create_resp.json()["id"]

    resp = await client.get(f"/ops/plans/{plan_id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["id"] == plan_id
    assert len(data["steps"]) == 3

    # Steps should be ordered by sequence
    sequences = [s["sequence"] for s in data["steps"]]
    assert sequences == sorted(sequences)

    # Each step should have full data
    first_step = data["steps"][0]
    assert first_step["name"] == "pull-image"
    assert first_step["action_type"] == "docker_pull"
    assert first_step["targets"] == ["vllm-primary"]
    assert first_step["params"] == {"image": "vllm/vllm-openai:v0.18.1"}


@pytest.mark.asyncio
async def test_get_plan_not_found(client):
    """Get a non-existent plan returns 404."""
    resp = await client.get("/ops/plans/PLN-NONEXIST")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_plan_rejects_empty_steps(client):
    """Plans must have at least one step."""
    payload = _make_plan_payload(steps=[])
    resp = await client.post("/ops/plans", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_plan_rejects_invalid_failure_policy(client):
    """Steps must use a valid failure_policy."""
    payload = _make_plan_payload(
        steps=[
            {
                "name": "bad-step",
                "sequence": 1,
                "action_type": "test",
                "targets": ["svc-a"],
                "failure_policy": "explode",
            }
        ]
    )
    resp = await client.post("/ops/plans", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_plan_rejects_excessive_expires_hours(client):
    """expires_hours must be <= 72."""
    payload = _make_plan_payload(expires_hours=100)
    resp = await client.post("/ops/plans", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cancel_draft_plan(client):
    """Cancel a draft plan."""
    create_resp = await client.post("/ops/plans", json=_make_plan_payload())
    plan_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "draft"

    resp = await client.post(f"/ops/plans/{plan_id}/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    assert data["id"] == plan_id


@pytest.mark.asyncio
async def test_cancel_already_cancelled_plan(client):
    """Cannot cancel an already cancelled plan."""
    create_resp = await client.post("/ops/plans", json=_make_plan_payload())
    plan_id = create_resp.json()["id"]

    # Cancel once
    await client.post(f"/ops/plans/{plan_id}/cancel")

    # Try again
    resp = await client.post(f"/ops/plans/{plan_id}/cancel")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_plan_not_found(client):
    """Cancel a non-existent plan returns 404."""
    resp = await client.post("/ops/plans/PLN-NONEXIST/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_depends_on_resolved_by_name(client):
    """Steps can reference dependencies by name, resolved to IDs."""
    payload = _make_plan_payload()
    resp = await client.post("/ops/plans", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    # Build a name-to-id map
    name_to_id = {s["name"]: s["id"] for s in data["steps"]}

    # "restart-service" depends on "pull-image"
    restart_step = next(s for s in data["steps"] if s["name"] == "restart-service")
    assert restart_step["depends_on"] == [name_to_id["pull-image"]]

    # "verify-health" depends on "restart-service"
    verify_step = next(s for s in data["steps"] if s["name"] == "verify-health")
    assert verify_step["depends_on"] == [name_to_id["restart-service"]]

    # "pull-image" has no dependencies
    pull_step = next(s for s in data["steps"] if s["name"] == "pull-image")
    assert pull_step["depends_on"] == []


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
        # Also seed plan.execute as AUTO
        await db.execute(
            "INSERT INTO ops_trust_ledger (action_type, total_count, success_count, failure_count, trust_tier) VALUES (?, 25, 25, 0, 'AUTO')",
            ("plan.execute",),
        )
        await db.commit()
    finally:
        await db.close()

    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Auto plan",
            "created_by": "nemoclaw",
            "steps": [
                {
                    "name": "check",
                    "sequence": 1,
                    "action_type": "health.check",
                    "targets": ["svc"],
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    resp = await client.post(
        f"/ops/plans/{plan_id}/approve", json={"approved_by": "nemoclaw"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["approval_method"] == "trust_ledger"
    assert data["approved_by"] == "nemoclaw"
    assert data["approved_at"] is not None


@pytest.mark.asyncio
async def test_approve_plan_needs_human(client):
    """Plan with ESCALATE-tier steps returns needs_approval."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Needs human",
            "created_by": "nemoclaw",
            "steps": [
                {
                    "name": "deploy",
                    "sequence": 1,
                    "action_type": "change.deploy",
                    "targets": ["svc"],
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    resp = await client.post(
        f"/ops/plans/{plan_id}/approve", json={"approved_by": "nemoclaw"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_approval"] is True
    assert len(data["escalated_steps"]) >= 1


@pytest.mark.asyncio
async def test_approve_plan_human_override(client):
    """Todd can force-approve a plan with ESCALATE steps."""
    create_resp = await client.post(
        "/ops/plans",
        json={
            "title": "Force",
            "created_by": "nemoclaw",
            "steps": [
                {
                    "name": "deploy",
                    "sequence": 1,
                    "action_type": "change.deploy",
                    "targets": ["svc"],
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    resp = await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
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
                {
                    "name": "s1",
                    "sequence": 1,
                    "action_type": "health.check",
                    "targets": ["svc"],
                }
            ],
        },
    )
    plan_id = create_resp.json()["id"]
    await client.post(f"/ops/plans/{plan_id}/cancel")
    resp = await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
    )
    assert resp.status_code == 409


# ---- Execution tests ----


async def _create_and_approve(client, **plan_overrides):
    """Helper: create a plan then force-approve it. Returns the plan dict."""
    payload = _make_plan_payload(**plan_overrides)
    create_resp = await client.post("/ops/plans", json=payload)
    assert create_resp.status_code == 201
    plan_id = create_resp.json()["id"]

    approve_resp = await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
    )
    data = approve_resp.json()
    # Handle both auto-approve and force-approve responses
    if "needs_approval" in data:
        approve_resp = await client.post(
            f"/ops/plans/{plan_id}/approve",
            json={"approved_by": "todd", "force": True},
        )
        data = approve_resp.json()
    assert data["status"] == "approved"
    return data


@pytest.mark.asyncio
async def test_execute_plan_creates_change_window(client):
    """Executing a plan creates a change window covering all targets."""
    plan = await _create_and_approve(client)
    plan_id = plan["id"]

    resp = await client.post(f"/ops/plans/{plan_id}/execute")
    assert resp.status_code == 200
    data = resp.json()

    # Plan should now be executing with a change_id
    assert data["status"] == "executing"
    assert data["change_id"] is not None
    assert data["change_id"].startswith("CHG-")

    # Verify the change window exists
    chg_resp = await client.get("/ops/changes", params={"status": "active"})
    changes = chg_resp.json()
    matching = [c for c in changes if c["id"] == data["change_id"]]
    assert len(matching) == 1
    assert set(matching[0]["targets"]) == set(plan["targets"])


@pytest.mark.asyncio
async def test_ready_steps_returns_dag_roots(client):
    """Ready steps endpoint returns only steps whose dependencies are met."""
    plan = await _create_and_approve(client)
    plan_id = plan["id"]

    # Execute the plan to mark root steps ready
    await client.post(f"/ops/plans/{plan_id}/execute")

    # Pull ready steps -- should be only "pull-image" (no deps)
    resp = await client.get(f"/ops/plans/{plan_id}/steps/ready")
    assert resp.status_code == 200
    ready = resp.json()
    assert len(ready) == 1
    assert ready[0]["name"] == "pull-image"
    assert ready[0]["status"] == "executing"  # claimed on pull


@pytest.mark.asyncio
async def test_step_completion_advances_dag(client):
    """Completing a step makes dependent steps ready."""
    plan = await _create_and_approve(client)
    plan_id = plan["id"]
    await client.post(f"/ops/plans/{plan_id}/execute")

    # Pull and complete root step
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    root_step_id = ready[0]["id"]

    result_resp = await client.post(
        f"/ops/plans/{plan_id}/steps/{root_step_id}/result",
        json={"success": True, "output": {"msg": "pulled"}},
    )
    assert result_resp.status_code == 200
    result = result_resp.json()
    assert result["step_status"] == "completed"
    assert len(result["next_ready_steps"]) == 1
    assert result["next_ready_steps"][0]["name"] == "restart-service"


@pytest.mark.asyncio
async def test_plan_completes_when_all_steps_done(client):
    """Plan status becomes completed when all steps succeed."""
    plan = await _create_and_approve(client)
    plan_id = plan["id"]
    await client.post(f"/ops/plans/{plan_id}/execute")

    # Walk the DAG: pull-image -> restart-service -> verify-health
    for _ in range(3):
        ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
        assert len(ready) == 1
        step_id = ready[0]["id"]
        await client.post(
            f"/ops/plans/{plan_id}/steps/{step_id}/result",
            json={"success": True},
        )

    # Check plan status
    status_resp = await client.get(f"/ops/plans/{plan_id}/status")
    assert status_resp.status_code == 200
    status = status_resp.json()
    assert status["status"] == "completed"
    assert status["completed"] == 3
    assert status["progress_pct"] == 100.0

    # Change window should also be closed
    plan_resp = await client.get(f"/ops/plans/{plan_id}")
    change_id = plan_resp.json()["change_id"]
    chg_resp = await client.get("/ops/changes", params={"status": "completed"})
    matching = [c for c in chg_resp.json() if c["id"] == change_id]
    assert len(matching) == 1
    assert matching[0]["outcome"] == "success"


@pytest.mark.asyncio
async def test_plan_status_endpoint(client):
    """Status endpoint returns step counts and progress."""
    plan = await _create_and_approve(client)
    plan_id = plan["id"]
    await client.post(f"/ops/plans/{plan_id}/execute")

    resp = await client.get(f"/ops/plans/{plan_id}/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["id"] == plan_id
    assert data["status"] == "executing"
    assert data["total_steps"] == 3
    assert data["ready"] == 1  # pull-image
    assert data["pending"] == 2  # restart-service, verify-health
    assert data["executing"] == 0
    assert data["completed"] == 0
    assert data["progress_pct"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_execute_non_approved_plan_fails(client):
    """Cannot execute a plan that isn't approved."""
    payload = _make_plan_payload()
    create_resp = await client.post("/ops/plans", json=payload)
    plan_id = create_resp.json()["id"]

    # Plan is in draft status -- execution should be rejected
    resp = await client.post(f"/ops/plans/{plan_id}/execute")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_parallel_roots_both_ready(client):
    """Multiple root steps (no deps) are all ready simultaneously."""
    payload = {
        "title": "Parallel roots",
        "created_by": "claude-code",
        "steps": [
            {
                "name": "root-a",
                "sequence": 1,
                "action_type": "health_check",
                "targets": ["svc-a"],
                "failure_policy": "halt",
            },
            {
                "name": "root-b",
                "sequence": 2,
                "action_type": "health_check",
                "targets": ["svc-b"],
                "failure_policy": "halt",
            },
            {
                "name": "join",
                "sequence": 3,
                "depends_on": ["root-a", "root-b"],
                "action_type": "health_check",
                "targets": ["svc-a", "svc-b"],
                "failure_policy": "halt",
            },
        ],
    }
    create_resp = await client.post("/ops/plans", json=payload)
    assert create_resp.status_code == 201
    plan_id = create_resp.json()["id"]

    # Force-approve
    approve_resp = await client.post(
        f"/ops/plans/{plan_id}/approve",
        json={"approved_by": "todd", "force": True},
    )
    data = approve_resp.json()
    if "needs_approval" in data:
        approve_resp = await client.post(
            f"/ops/plans/{plan_id}/approve",
            json={"approved_by": "todd", "force": True},
        )
    assert approve_resp.json()["status"] == "approved"

    # Execute
    await client.post(f"/ops/plans/{plan_id}/execute")

    # Both roots should be ready
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    ready_names = {s["name"] for s in ready}
    assert ready_names == {"root-a", "root-b"}

    # Complete both roots
    for step in ready:
        await client.post(
            f"/ops/plans/{plan_id}/steps/{step['id']}/result",
            json={"success": True},
        )

    # Now the join step should be ready
    ready2 = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    assert len(ready2) == 1
    assert ready2[0]["name"] == "join"


# ---- Failure policy tests ----


async def _create_approve_execute(client, **plan_overrides):
    """Helper: create, force-approve, and execute a plan. Returns the plan dict."""
    plan = await _create_and_approve(client, **plan_overrides)
    plan_id = plan["id"]
    exec_resp = await client.post(f"/ops/plans/{plan_id}/execute")
    assert exec_resp.status_code == 200
    return exec_resp.json()


@pytest.mark.asyncio
async def test_halt_policy_blocks_plan(client):
    """A failed step with halt policy blocks the plan."""
    plan = await _create_approve_execute(
        client,
        steps=[
            {
                "name": "step-a",
                "sequence": 1,
                "action_type": "docker_pull",
                "targets": ["svc-a"],
                "failure_policy": "halt",
            },
            {
                "name": "step-b",
                "sequence": 2,
                "depends_on": ["step-a"],
                "action_type": "docker_restart",
                "targets": ["svc-a"],
                "failure_policy": "halt",
            },
        ],
    )
    plan_id = plan["id"]

    # Claim root step
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    assert len(ready) == 1
    step_a_id = ready[0]["id"]

    # Report failure
    result = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_a_id}/result",
        json={"success": False, "error": "image not found"},
    )
    assert result.status_code == 200
    data = result.json()

    assert data["step_status"] == "failed"
    assert data["plan_status"] == "blocked"
    assert data["next_ready_steps"] == []

    # step-b should still be pending -- NOT ready
    plan_resp = await client.get(f"/ops/plans/{plan_id}")
    step_b = next(s for s in plan_resp.json()["steps"] if s["name"] == "step-b")
    assert step_b["status"] == "pending"


@pytest.mark.asyncio
async def test_skip_policy_continues(client):
    """A failed step with skip policy allows the plan to continue."""
    plan = await _create_approve_execute(
        client,
        steps=[
            {
                "name": "step-a",
                "sequence": 1,
                "action_type": "health_check",
                "targets": ["svc-a"],
                "failure_policy": "skip",
            },
            {
                "name": "step-b",
                "sequence": 2,
                "depends_on": ["step-a"],
                "action_type": "docker_restart",
                "targets": ["svc-a"],
                "failure_policy": "halt",
            },
        ],
    )
    plan_id = plan["id"]

    # Claim and fail step-a (skip policy)
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    step_a_id = ready[0]["id"]

    result = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_a_id}/result",
        json={"success": False, "error": "non-critical failure"},
    )
    data = result.json()

    # Step should be marked skipped, not failed
    assert data["step_status"] == "skipped"
    assert data["plan_status"] == "executing"

    # step-b should now be ready (skipped counts as "done" for dependencies)
    assert len(data["next_ready_steps"]) == 1
    assert data["next_ready_steps"][0]["name"] == "step-b"


@pytest.mark.asyncio
async def test_retry_policy(client):
    """A failed step with retry policy re-queues up to max_retries, then halts."""
    plan = await _create_approve_execute(
        client,
        steps=[
            {
                "name": "flaky-step",
                "sequence": 1,
                "action_type": "health_check",
                "targets": ["svc-a"],
                "failure_policy": "retry",
                "max_retries": 2,
            },
            {
                "name": "next-step",
                "sequence": 2,
                "depends_on": ["flaky-step"],
                "action_type": "docker_restart",
                "targets": ["svc-a"],
                "failure_policy": "halt",
            },
        ],
    )
    plan_id = plan["id"]

    # Retry 1: claim and fail
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    step_id = ready[0]["id"]

    result = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_id}/result",
        json={"success": False, "error": "transient failure"},
    )
    data = result.json()
    assert data["step_status"] == "ready"
    assert data["retry_count"] == 1
    assert data["plan_status"] == "executing"

    # Retry 2: claim and fail again
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    assert len(ready) == 1
    step_id = ready[0]["id"]

    result = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_id}/result",
        json={"success": False, "error": "transient failure 2"},
    )
    data = result.json()
    assert data["step_status"] == "ready"
    assert data["retry_count"] == 2
    assert data["plan_status"] == "executing"

    # Retry 3: max reached -- should halt
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    step_id = ready[0]["id"]

    result = await client.post(
        f"/ops/plans/{plan_id}/steps/{step_id}/result",
        json={"success": False, "error": "still failing"},
    )
    data = result.json()
    assert data["step_status"] == "failed"
    assert data["retry_count"] == 3
    assert data["plan_status"] == "blocked"


@pytest.mark.asyncio
async def test_rollback_reverses_completed_steps(client):
    """Triggering rollback creates rollback steps in reverse order."""
    plan = await _create_approve_execute(
        client,
        steps=[
            {
                "name": "deploy-image",
                "sequence": 1,
                "action_type": "docker_pull",
                "targets": ["svc-a"],
                "failure_policy": "halt",
                "rollback": {"action_type": "docker_pull", "params": {"image": "old:v1"}},
            },
            {
                "name": "restart-svc",
                "sequence": 2,
                "depends_on": ["deploy-image"],
                "action_type": "docker_restart",
                "targets": ["svc-a"],
                "failure_policy": "halt",
                "rollback": {"action_type": "docker_restart", "params": {}},
            },
            {
                "name": "verify",
                "sequence": 3,
                "depends_on": ["restart-svc"],
                "action_type": "health_check",
                "targets": ["svc-a"],
                "failure_policy": "halt",
                # No rollback for verification step
            },
        ],
    )
    plan_id = plan["id"]

    # Complete steps 1 and 2, fail step 3
    for _ in range(2):
        ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
        step_id = ready[0]["id"]
        await client.post(
            f"/ops/plans/{plan_id}/steps/{step_id}/result",
            json={"success": True},
        )

    # Fail step 3 (halt policy) -> plan blocked
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    step_id = ready[0]["id"]
    await client.post(
        f"/ops/plans/{plan_id}/steps/{step_id}/result",
        json={"success": False, "error": "health check failed"},
    )

    # Trigger rollback
    rb_resp = await client.post(f"/ops/plans/{plan_id}/rollback")
    assert rb_resp.status_code == 200
    data = rb_resp.json()

    assert data["status"] == "rolling_back"

    # Should have rollback steps for deploy-image and restart-svc (reverse order)
    # restart-svc was seq 2, deploy-image was seq 1
    # Rollback order: restart-svc first (seq -2), then deploy-image (seq -1)
    rb_steps = [s for s in data["steps"] if s["name"].startswith("rollback:")]
    assert len(rb_steps) == 2

    # Verify reverse order via sequence
    rb_names = [s["name"] for s in sorted(rb_steps, key=lambda s: s["sequence"])]
    assert rb_names == ["rollback:restart-svc", "rollback:deploy-image"]

    # First rollback step should be ready, second pending
    rb_sorted = sorted(rb_steps, key=lambda s: s["sequence"])
    assert rb_sorted[0]["status"] == "ready"
    assert rb_sorted[1]["status"] == "pending"

    # Rollback steps should have halt failure_policy
    assert all(s["failure_policy"] == "halt" for s in rb_steps)


@pytest.mark.asyncio
async def test_rollback_completes_plan_as_rolled_back(client):
    """Completing all rollback steps sets plan outcome to rolled_back."""
    plan = await _create_approve_execute(
        client,
        steps=[
            {
                "name": "deploy",
                "sequence": 1,
                "action_type": "docker_pull",
                "targets": ["svc-a"],
                "failure_policy": "halt",
                "rollback": {"action_type": "docker_pull", "params": {"image": "old:v1"}},
            },
            {
                "name": "verify",
                "sequence": 2,
                "depends_on": ["deploy"],
                "action_type": "health_check",
                "targets": ["svc-a"],
                "failure_policy": "halt",
            },
        ],
    )
    plan_id = plan["id"]

    # Complete step 1, fail step 2 -> blocked
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    await client.post(
        f"/ops/plans/{plan_id}/steps/{ready[0]['id']}/result",
        json={"success": True},
    )

    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    await client.post(
        f"/ops/plans/{plan_id}/steps/{ready[0]['id']}/result",
        json={"success": False, "error": "health check failed"},
    )

    # Trigger rollback
    await client.post(f"/ops/plans/{plan_id}/rollback")

    # Complete all rollback steps
    ready = (await client.get(f"/ops/plans/{plan_id}/steps/ready")).json()
    assert len(ready) == 1
    assert ready[0]["name"].startswith("rollback:")

    await client.post(
        f"/ops/plans/{plan_id}/steps/{ready[0]['id']}/result",
        json={"success": True},
    )

    # Plan should be completed with rolled_back outcome
    plan_resp = await client.get(f"/ops/plans/{plan_id}")
    plan_data = plan_resp.json()
    assert plan_data["status"] == "failed"
    assert plan_data["outcome"] == "rolled_back"


@pytest.mark.asyncio
async def test_rollback_rejects_executing_plan(client):
    """Cannot rollback a plan that is still executing."""
    plan = await _create_approve_execute(client)
    plan_id = plan["id"]

    resp = await client.post(f"/ops/plans/{plan_id}/rollback")
    assert resp.status_code == 409
