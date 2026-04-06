"""End-to-end integration tests — multi-agent coordination scenarios.

These tests simulate real operational workflows where multiple agents
interact through Corvus.
"""

import pytest


@pytest.mark.asyncio
async def test_change_window_prevents_conflict(client):
    """Agent A declares change → Agent B sees CAUTION on target status."""
    # Agent A: declare change window
    change = await client.post(
        "/ops/changes",
        json={
            "targets": ["litellm"],
            "description": "Deploying new proxy config",
            "created_by": "claude-code",
        },
    )
    assert change.status_code == 201
    change_id = change.json()["id"]

    # Agent B: check target before acting
    status = await client.get("/ops/events/targets/litellm/status")
    assert status.json()["recommendation"] in ("CAUTION", "STOP")
    assert len(status.json()["active_changes"]) == 1

    # Agent A: close change
    close = await client.patch(
        f"/ops/changes/{change_id}",
        json={
            "status": "completed",
            "outcome": "success",
        },
    )
    assert close.status_code == 200

    # Agent B: target is now clear
    status = await client.get("/ops/events/targets/litellm/status")
    assert status.json()["recommendation"] == "GO"


@pytest.mark.asyncio
async def test_incident_creates_stop_for_other_agents(client):
    """Agent A creates critical incident → Agent B sees STOP."""
    # ops-agent: detect failure
    inc = await client.post(
        "/ops/incidents",
        json={
            "target": "vllm-primary",
            "title": "CUDA OOM — GPU VRAM exhausted",
            "severity": "critical",
            "detected_by": "ops-agent:health_sweep",
        },
    )
    incident_id = inc.json()["id"]

    # ops-agent: emit event
    await client.post(
        "/ops/events",
        json={
            "source": "ops-agent",
            "type": "incident.opened",
            "target": "vllm-primary",
            "severity": "critical",
            "data": {"summary": "CUDA OOM on vllm-primary"},
            "related_incident_id": incident_id,
        },
    )

    # Claude Code: check before acting
    status = await client.get("/ops/events/targets/vllm-primary/status")
    assert status.json()["recommendation"] == "STOP"
    assert "CUDA OOM" in status.json()["reason"]

    # ops-agent: resolve
    await client.patch(
        f"/ops/incidents/{incident_id}",
        json={
            "status": "resolved",
            "root_cause": "GPU memory leak",
            "remediation_applied": "Restarted container",
        },
    )

    # Claude Code: target now clear (no open/investigating incidents)
    status = await client.get("/ops/events/targets/vllm-primary/status")
    # After resolution, no active incidents remain
    assert len(status.json()["active_incidents"]) == 0


@pytest.mark.asyncio
async def test_event_emission_creates_shared_awareness(client):
    """Agent A emits event → Agent B sees it in context briefing."""
    # Claude Code: deploy change
    await client.post(
        "/ops/events",
        json={
            "source": "claude-code",
            "type": "change.completed",
            "target": "admin-api",
            "severity": "info",
            "data": {"summary": "Deployed OCSF transformer v2"},
        },
    )

    # ops-agent: check context at sweep start
    context = await client.get("/ops/events/context")
    data = context.json()
    events = data["events_24h"]
    targets = [e["target"] for e in events]
    assert "admin-api" in targets


@pytest.mark.asyncio
async def test_full_incident_lifecycle_with_gap_detection(client):
    """Full lifecycle: detect → investigate → resolve → gap detection."""
    # Register service
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "postgres-main",
            "service_type": "database",
            "critical": True,
        },
    )

    # Detect issue
    inc = await client.post(
        "/ops/incidents",
        json={
            "target": "postgres-main",
            "title": "Connection pool exhausted",
            "severity": "high",
            "detected_by": "ops-agent:health_sweep",
        },
    )
    incident_id = inc.json()["id"]

    # Investigate
    await client.patch(
        f"/ops/incidents/{incident_id}",
        json={
            "status": "investigating",
            "investigation_summary": "Active connections at max_connections limit",
        },
    )

    # Resolve WITHOUT root cause — should trigger gap
    await client.patch(
        f"/ops/incidents/{incident_id}",
        json={
            "status": "resolved",
        },
    )

    # Verify gap was created
    problems = await client.get("/ops/problems", params={"pattern": "gap:accuracy"})
    gaps = [p for p in problems.json() if "postgres-main" in (p["pattern"] or "")]
    assert len(gaps) >= 1
    assert gaps[0]["workstream"] == "CI"


@pytest.mark.asyncio
async def test_triage_driven_incident_handling(client):
    """Service detected unhealthy → triage → incident → resolution."""
    # Register service
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "vllm-test",
            "host": "gpu-host-1",
            "service_type": "inference",
        },
    )

    # Run triage with investigation data
    triage = await client.post(
        "/ops/runbooks/triage",
        json={
            "target": "vllm-test",
            "investigation_data": {"logs": "CUDA error: out of memory on device 0"},
        },
    )
    triage_data = triage.json()
    assert triage_data["diagnosis"] == "gpu_oom"
    assert triage_data["restart_safe"] is False

    # Create incident based on triage
    inc = await client.post(
        "/ops/incidents",
        json={
            "target": "vllm-test",
            "title": f"Triage: {triage_data['diagnosis']} on vllm-test",
            "severity": "critical",
            "detected_by": "ops-agent",
        },
    )

    # Emit event
    await client.post(
        "/ops/events",
        json={
            "source": "ops-agent",
            "type": "incident.escalated",
            "target": "vllm-test",
            "severity": "critical",
            "data": {
                "summary": triage_data["explanation"],
                "runbook": triage_data["runbook_name"],
                "diagnosis": triage_data["diagnosis"],
            },
            "related_incident_id": inc.json()["id"],
        },
    )

    # Verify metrics reflect the incident
    metrics = await client.get("/ops/metrics")
    assert metrics.json()["open_incidents"] >= 1


@pytest.mark.asyncio
async def test_problem_correlation_across_incidents(client):
    """Multiple incidents on same target → correlated to single problem."""
    # Create problem
    prb = await client.post(
        "/ops/problems",
        json={
            "title": "Recurring OOM on inference services",
            "pattern": "recurring:oom:inference",
            "workstream": "CI",
        },
    )
    problem_id = prb.json()["id"]

    # Create multiple incidents and correlate
    for i in range(3):
        inc = await client.post(
            "/ops/incidents",
            json={
                "target": f"vllm-{i}",
                "title": f"OOM on vllm-{i}",
                "severity": "high",
                "detected_by": "ops-agent",
            },
        )
        await client.post(
            "/ops/problems/correlate",
            json={
                "incident_id": inc.json()["id"],
                "problem_id": problem_id,
            },
        )

    # Verify all correlated
    problems = await client.get("/ops/problems")
    problem = [p for p in problems.json() if p["id"] == problem_id][0]
    assert len(problem["correlated_incidents"]) == 3


@pytest.mark.asyncio
async def test_metrics_dashboard(client):
    """Verify metrics endpoint returns comprehensive operational data."""
    # Seed data
    await client.post("/ops/cmdb/register", json={"name": "metrics-test", "service_type": "utility"})
    await client.post("/ops/cmdb/register", json={"name": "metrics-test-2"})  # untyped
    await client.post(
        "/ops/incidents",
        json={
            "target": "metrics-test",
            "title": "Test",
            "detected_by": "test",
        },
    )
    await client.post(
        "/ops/events",
        json={
            "source": "test",
            "type": "test.event",
            "target": "metrics-test",
        },
    )

    metrics = await client.get("/ops/metrics")
    data = metrics.json()

    # Core metrics
    assert data["events_24h"] >= 1
    assert data["open_incidents"] >= 1
    assert data["total_services"] >= 2
    assert data["untyped_services"] >= 1
    assert "false_positive_rate" in data
    assert "gaps_by_workstream" in data

    # SIEM stats
    assert "siem" in data
    assert "siem_configured" in data["siem"]

    # Runbook coverage
    assert "runbook_coverage" in data
    assert "inference" in data["runbook_coverage"]["covered_service_types"]
