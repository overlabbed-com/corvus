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
