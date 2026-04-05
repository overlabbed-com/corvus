"""Tests for automated gap detection."""

import pytest


@pytest.mark.asyncio
async def test_gap_on_resolve_without_root_cause(client):
    """Resolving an incident without root cause should create a gap."""
    # Create incident
    inc = await client.post(
        "/ops/incidents",
        json={
            "target": "svc-gap-test",
            "title": "Mysterious failure",
            "detected_by": "test",
        },
    )
    incident_id = inc.json()["id"]

    # Resolve without root_cause
    await client.patch(
        f"/ops/incidents/{incident_id}",
        json={
            "status": "resolved",
        },
    )

    # Check that gap problem was created
    resp = await client.get("/ops/problems", params={"pattern": "gap:accuracy:unclassifiable"})
    problems = resp.json()
    matching = [p for p in problems if "svc-gap-test" in (p["pattern"] or "")]
    assert len(matching) >= 1
    assert matching[0]["workstream"] == "CI"


@pytest.mark.asyncio
async def test_gap_on_resolve_without_remediation(client):
    """Resolving without remediation should create a manual-resolution gap."""
    inc = await client.post(
        "/ops/incidents",
        json={
            "target": "svc-noremed",
            "title": "Fixed manually",
            "detected_by": "test",
        },
    )
    incident_id = inc.json()["id"]

    await client.patch(
        f"/ops/incidents/{incident_id}",
        json={
            "status": "resolved",
            "root_cause": "Config error",
        },
    )

    resp = await client.get("/ops/problems", params={"pattern": "gap:autonomy"})
    problems = resp.json()
    matching = [p for p in problems if "svc-noremed" in (p["pattern"] or "")]
    assert len(matching) >= 1


@pytest.mark.asyncio
async def test_gap_deduplication(client):
    """Duplicate gaps should append to correlated_incidents, not create new."""
    for i in range(2):
        inc = await client.post(
            "/ops/incidents",
            json={
                "target": "svc-dedup",
                "title": f"Failure {i}",
                "detected_by": "test",
            },
        )
        await client.patch(
            f"/ops/incidents/{inc.json()['id']}",
            json={
                "status": "resolved",
            },
        )

    resp = await client.get("/ops/problems", params={"pattern": "gap:accuracy:unclassifiable:svc-dedup"})
    problems = resp.json()
    # Should be exactly one gap, not two
    assert len(problems) == 1
    # Should have both incidents correlated
    assert len(problems[0]["correlated_incidents"]) == 2
