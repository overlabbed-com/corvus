"""Tests for the module loader and SOC 2 compliance module."""

import pytest


@pytest.mark.asyncio
async def test_modules_listing(client):
    """GET /ops/modules returns loaded modules."""
    resp = await client.get("/ops/modules")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # SOC 2 module should be loaded
    names = [m["name"] for m in data]
    assert "soc2" in names


@pytest.mark.asyncio
async def test_soc2_module_metadata(client):
    """SOC 2 module has correct metadata."""
    resp = await client.get("/ops/modules")
    data = resp.json()
    soc2 = next(m for m in data if m["name"] == "soc2")
    assert soc2["type"] == "compliance"
    assert soc2["active"] is True
    assert soc2["has_router"] is True


@pytest.mark.asyncio
async def test_soc2_controls_listing(client):
    """GET /ops/modules/soc2/controls lists all controls."""
    resp = await client.get("/ops/modules/soc2/controls")
    assert resp.status_code == 200
    data = resp.json()
    # Should have CC6, CC7, CC8, CC9 controls
    assert "CC6.1" in data
    assert "CC7.1" in data
    assert "CC8.1" in data
    assert "CC9.1" in data


@pytest.mark.asyncio
async def test_soc2_single_control_check(client):
    """GET /ops/modules/soc2/controls/{id} runs a single check."""
    resp = await client.get("/ops/modules/soc2/controls/CC7.3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["control_id"] == "CC7.3"
    assert "status" in data
    assert "evidence" in data


@pytest.mark.asyncio
async def test_soc2_unknown_control(client):
    """Unknown control ID returns 404."""
    resp = await client.get("/ops/modules/soc2/controls/CC99.1")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_soc2_audit_empty_db(client):
    """SOC 2 audit on empty DB returns structured results."""
    resp = await client.get("/ops/modules/soc2/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["framework"] == "SOC 2 Type II"
    assert "summary" in data
    assert "controls" in data
    assert "compliance_rate" in data
    # Controls should all be assessed
    assert len(data["controls"]) == 12  # 3 CC6 + 4 CC7 + 3 CC8 + 2 CC9


@pytest.mark.asyncio
async def test_soc2_audit_with_data(client):
    """SOC 2 audit with operational data produces evidence."""
    # Emit an event and create a change to produce audit evidence
    await client.post(
        "/ops/events",
        json={"source": "test", "type": "test.event", "target": "svc-a", "severity": "info", "data": {}},
    )
    await client.post(
        "/ops/changes",
        json={
            "targets": ["svc-a"],
            "description": "Test change",
            "created_by": "test-operator",
            "rollback_plan": "Revert",
        },
    )
    await client.post(
        "/ops/cmdb/register",
        json={"name": "audit-svc", "service_type": "proxy", "host": "test"},
    )

    resp = await client.get("/ops/modules/soc2/audit?days=1")
    assert resp.status_code == 200
    data = resp.json()

    # CC7.1 should pass (events exist)
    cc71 = data["controls"]["CC7.1"]
    assert cc71["status"] == "pass"
    assert cc71["evidence"]["total_events"] >= 1

    # CC8.1 should pass (change has attribution)
    cc81 = data["controls"]["CC8.1"]
    assert cc81["evidence"]["total_changes"] >= 1


@pytest.mark.asyncio
async def test_soc2_audit_custom_window(client):
    """SOC 2 audit respects custom audit window."""
    resp = await client.get("/ops/modules/soc2/audit?days=7")
    assert resp.status_code == 200
    assert resp.json()["audit_window_days"] == 7
