"""Tests for agent-side step execution protocol."""

import pytest


@pytest.mark.asyncio
async def test_list_pending_steps_empty(client):
    """No pending steps returns empty list."""
    resp = await client.get("/ops/runbooks/steps/pending")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_and_list_pending_steps(client):
    """Steps created via create_pending_steps appear in listing."""
    from src.routers.steps import create_pending_steps

    steps = [
        {"name": "check_logs", "type": "containers.logs", "params": {"container": "vllm"}, "timeout": 30},
        {"name": "check_gpu", "type": "gpu.nvidia_smi", "params": {"host": "dockp01"}, "timeout": 15},
    ]
    created = await create_pending_steps("TRG-TEST0001", steps, {"target": "vllm", "host": "dockp01"})
    assert len(created) == 2
    assert created[0]["step_type"] == "containers.logs"
    assert created[1]["step_type"] == "gpu.nvidia_smi"

    resp = await client.get("/ops/runbooks/steps/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(s["status"] == "pending" for s in data)


@pytest.mark.asyncio
async def test_submit_step_result_success(client):
    """Agent can submit successful step result."""
    from src.routers.steps import create_pending_steps

    steps = [{"name": "check_logs", "type": "containers.logs", "params": {}, "timeout": 30}]
    created = await create_pending_steps("TRG-TEST0002", steps, {})
    step_id = created[0]["step_id"]

    resp = await client.post(
        f"/ops/runbooks/steps/{step_id}/result",
        json={"output": {"logs": "OK", "lines": 50}, "success": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["all_steps_complete"] is True

    # Step no longer appears in pending for this triage
    resp = await client.get("/ops/runbooks/steps/pending?triage_id=TRG-TEST0002")
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_submit_step_result_failure(client):
    """Agent can submit failed step result."""
    from src.routers.steps import create_pending_steps

    steps = [{"name": "check_gpu", "type": "gpu.nvidia_smi", "params": {}, "timeout": 15}]
    created = await create_pending_steps("TRG-TEST0003", steps, {})
    step_id = created[0]["step_id"]

    resp = await client.post(
        f"/ops/runbooks/steps/{step_id}/result",
        json={"success": False, "error": "SSH connection refused"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"


@pytest.mark.asyncio
async def test_submit_step_result_not_found(client):
    """Submitting to nonexistent step returns 404."""
    resp = await client.post(
        "/ops/runbooks/steps/STEP-NOTFOUND/result",
        json={"output": {}, "success": True},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submit_step_result_already_completed(client):
    """Submitting to already-completed step returns 409."""
    from src.routers.steps import create_pending_steps

    steps = [{"name": "check", "type": "host.check", "params": {}, "timeout": 10}]
    created = await create_pending_steps("TRG-TEST0004", steps, {})
    step_id = created[0]["step_id"]

    # First submission
    await client.post(
        f"/ops/runbooks/steps/{step_id}/result",
        json={"output": {"ok": True}, "success": True},
    )

    # Second submission — conflict
    resp = await client.post(
        f"/ops/runbooks/steps/{step_id}/result",
        json={"output": {"ok": True}, "success": True},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_step_details(client):
    """GET /steps/{step_id} returns step details."""
    from src.routers.steps import create_pending_steps

    steps = [{"name": "check_mqtt", "type": "mqtt.check", "params": {"topic": "$SYS"}, "timeout": 5}]
    created = await create_pending_steps("TRG-TEST0005", steps, {})
    step_id = created[0]["step_id"]

    resp = await client.get(f"/ops/runbooks/steps/{step_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["step_name"] == "check_mqtt"
    assert data["step_type"] == "mqtt.check"
    assert data["params"]["topic"] == "$SYS"


@pytest.mark.asyncio
async def test_pending_steps_filter_by_triage(client):
    """Pending steps can be filtered by triage_id."""
    from src.routers.steps import create_pending_steps

    await create_pending_steps("TRG-AAA", [{"name": "s1", "type": "host.check", "params": {}}], {})
    await create_pending_steps("TRG-BBB", [{"name": "s2", "type": "host.check", "params": {}}], {})

    resp = await client.get("/ops/runbooks/steps/pending?triage_id=TRG-AAA")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["triage_id"] == "TRG-AAA"


@pytest.mark.asyncio
async def test_all_steps_complete_tracking(client):
    """all_steps_complete is False until all steps for a triage are done."""
    from src.routers.steps import create_pending_steps

    steps = [
        {"name": "s1", "type": "host.check", "params": {}},
        {"name": "s2", "type": "containers.logs", "params": {}},
    ]
    created = await create_pending_steps("TRG-MULTI", steps, {})

    # Submit first step
    resp = await client.post(
        f"/ops/runbooks/steps/{created[0]['step_id']}/result",
        json={"output": {"ok": True}, "success": True},
    )
    data = resp.json()
    assert data["all_steps_complete"] is False
    assert data["pending_steps"] == 1

    # Submit second step
    resp = await client.post(
        f"/ops/runbooks/steps/{created[1]['step_id']}/result",
        json={"output": {"ok": True}, "success": True},
    )
    data = resp.json()
    assert data["all_steps_complete"] is True
    assert data["pending_steps"] == 0


@pytest.mark.asyncio
async def test_template_substitution(client):
    """Step params get template variables resolved."""
    from src.routers.steps import create_pending_steps

    steps = [
        {
            "name": "check_logs",
            "type": "containers.logs",
            "params": {"container": "{{ target }}", "host": "{{host}}"},
        },
    ]
    created = await create_pending_steps("TRG-TMPL", steps, {"target": "vllm-primary", "host": "dockp01"})
    assert created[0]["params"]["container"] == "vllm-primary"
    assert created[0]["params"]["host"] == "dockp01"


@pytest.mark.asyncio
async def test_async_triage_endpoint(client):
    """POST /steps/triage/async starts async triage with pending steps."""
    # Register a service with a known type that has a runbook
    await client.post(
        "/ops/cmdb/register",
        json={"name": "test-inference", "service_type": "inference", "host": "test"},
    )

    resp = await client.post(
        "/ops/runbooks/steps/triage/async",
        json={"target": "test-inference", "service_type": "inference"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "awaiting_steps"
    assert "triage_id" in data
    assert "pending_steps" in data
    assert isinstance(data["pending_steps"], list)


@pytest.mark.asyncio
async def test_async_triage_no_service_type(client):
    """Async triage with no service_type and no CMDB entry returns 400."""
    resp = await client.post(
        "/ops/runbooks/steps/triage/async",
        json={"target": "unknown-svc"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_continue_triage_not_found(client):
    """Continue triage with bad ID returns 404."""
    resp = await client.post("/ops/runbooks/steps/triage/TRG-NOPE/continue")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_full_async_triage_flow(client):
    """Full flow: start async triage → submit step results → continue → get diagnosis."""
    # Register service
    await client.post(
        "/ops/cmdb/register",
        json={"name": "test-proxy-async", "service_type": "proxy", "host": "test"},
    )

    # Start async triage
    resp = await client.post(
        "/ops/runbooks/steps/triage/async",
        json={"target": "test-proxy-async", "service_type": "proxy"},
    )
    assert resp.status_code == 200
    triage_data = resp.json()
    triage_id = triage_data["triage_id"]
    pending = triage_data["pending_steps"]

    # Submit all step results
    for step in pending:
        resp = await client.post(
            f"/ops/runbooks/steps/{step['step_id']}/result",
            json={"output": {"status": "ok"}, "success": True},
        )
        assert resp.status_code == 200

    # Continue triage — get diagnosis
    resp = await client.post(f"/ops/runbooks/steps/triage/{triage_id}/continue")
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "triaged"
    assert "diagnosis" in result
    assert "confidence" in result
    assert result["triage_id"] == triage_id
