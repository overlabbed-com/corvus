"""Tests for problems API."""

import pytest


@pytest.mark.asyncio
async def test_create_problem(client):
    resp = await client.post(
        "/ops/problems",
        json={
            "title": "Unclassifiable failure on vllm-primary",
            "pattern": "gap:accuracy:unclassifiable:vllm-primary",
            "root_cause": "Agent couldn't determine root cause",
            "recommended_fix": "CI: Add new diagnosis rule",
            "severity": "medium",
            "workstream": "CI",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"].startswith("PRB-")
    assert data["status"] == "identified"
    assert data["workstream"] == "CI"


@pytest.mark.asyncio
async def test_list_problems_by_workstream(client):
    await client.post(
        "/ops/problems",
        json={
            "title": "Gap 1",
            "pattern": "gap:coverage:no-runbook",
            "workstream": "NFI",
        },
    )
    await client.post(
        "/ops/problems",
        json={
            "title": "Gap 2",
            "pattern": "gap:accuracy:wrong",
            "workstream": "CI",
        },
    )

    resp = await client.get("/ops/problems", params={"workstream": "NFI"})
    assert resp.status_code == 200
    problems = resp.json()
    assert all(p["workstream"] == "NFI" for p in problems)


@pytest.mark.asyncio
async def test_correlate_incident_to_problem(client):
    inc = await client.post(
        "/ops/incidents",
        json={
            "target": "svc-x",
            "title": "Failure",
            "detected_by": "test",
        },
    )
    prb = await client.post(
        "/ops/problems",
        json={
            "title": "Recurring failure pattern",
        },
    )

    resp = await client.post(
        "/ops/problems/correlate",
        json={
            "incident_id": inc.json()["id"],
            "problem_id": prb.json()["id"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "correlated"

    # Verify the link
    inc_resp = await client.get(f"/ops/incidents/{inc.json()['id']}")
    assert inc_resp.json()["correlated_to_problem"] == prb.json()["id"]
