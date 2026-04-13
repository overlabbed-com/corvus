"""Tests for Configuration Item (CI) functionality."""

from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.asyncio
async def test_register_ci(client):
    """Test registering a new CI."""
    ci_data = {
        "name": "test-cert-2026",
        "ci_type": "cert",
        "service_name": "caddy",
        "expires_at": "2026-10-15T00:00:00Z",
        "metadata": {"issuer": "Let's Encrypt"},
    }

    resp = await client.post("/ops/cmdb/ci", json=ci_data)
    assert resp.status_code == 201

    data = resp.json()
    assert data["name"] == "test-cert-2026"
    assert data["ci_type"] == "cert"
    assert data["service_name"] == "caddy"
    assert data["expires_at"] == "2026-10-15T00:00:00Z"
    assert data["operational_status"] == "active"
    assert data["metadata"]["issuer"] == "Let's Encrypt"


@pytest.mark.asyncio
async def test_register_ci_without_expiry(client):
    """Test registering a CI without expiry (e.g., a credential)."""
    ci_data = {
        "name": "powerdns-api-key",
        "ci_type": "credential",
        "service_name": "powerdns",
        "metadata": {"rotation_schedule": "90-days"},
    }

    resp = await client.post("/ops/cmdb/ci", json=ci_data)
    assert resp.status_code == 201

    data = resp.json()
    assert data["name"] == "powerdns-api-key"
    assert data["ci_type"] == "credential"
    assert data["expires_at"] is None


@pytest.mark.asyncio
async def test_update_existing_ci(client):
    """Test updating an existing CI."""
    # Register initial CI
    ci_data = {"name": "test-cert", "ci_type": "cert", "expires_at": "2026-06-01T00:00:00Z"}
    await client.post("/ops/cmdb/ci", json=ci_data)

    # Update the CI
    update_data = {
        "name": "test-cert",
        "ci_type": "cert",
        "expires_at": "2027-06-01T00:00:00Z",
        "operational_status": "expiring",
    }

    resp = await client.post("/ops/cmdb/ci", json=update_data)
    assert resp.status_code == 201

    data = resp.json()
    assert data["expires_at"] == "2027-06-01T00:00:00Z"
    assert data["operational_status"] == "expiring"


@pytest.mark.asyncio
async def test_get_ci(client):
    """Test getting CI details."""
    # Register CI
    ci_data = {"name": "test-zone", "ci_type": "zone", "metadata": {"records": 42}}
    await client.post("/ops/cmdb/ci", json=ci_data)

    # Get CI
    resp = await client.get("/ops/cmdb/ci/test-zone")
    assert resp.status_code == 200

    data = resp.json()
    assert data["name"] == "test-zone"
    assert data["ci_type"] == "zone"


@pytest.mark.asyncio
async def test_get_ci_not_found(client):
    """Test getting non-existent CI."""
    resp = await client.get("/ops/cmdb/ci/non-existent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_ci_with_expiry(client):
    """Test that days_until_expiry is calculated correctly."""
    future_date = (datetime.now(UTC) + timedelta(days=100)).isoformat()
    ci_data = {"name": "expiring-cert", "ci_type": "cert", "expires_at": future_date}

    resp = await client.post("/ops/cmdb/ci", json=ci_data)
    assert resp.status_code == 201

    data = resp.json()
    assert data["days_until_expiry"] is not None
    assert 95 <= data["days_until_expiry"] <= 100


@pytest.mark.asyncio
async def test_list_cis(client):
    """Test listing all CIs."""
    # Register multiple CIs
    await client.post("/ops/cmdb/ci", json={"name": "cert-1", "ci_type": "cert"})
    await client.post("/ops/cmdb/ci", json={"name": "cred-1", "ci_type": "credential"})
    await client.post("/ops/cmdb/ci", json={"name": "zone-1", "ci_type": "zone"})

    resp = await client.get("/ops/cmdb/ci")
    assert resp.status_code == 200

    data = resp.json()
    assert len(data) >= 3


@pytest.mark.asyncio
async def test_list_cis_filter_by_type(client):
    """Test filtering CIs by type."""
    # Use unique names to avoid conflicts with other tests
    await client.post("/ops/cmdb/ci", json={"name": "filter-cert-1", "ci_type": "cert"})
    await client.post("/ops/cmdb/ci", json={"name": "filter-cert-2", "ci_type": "cert"})
    await client.post("/ops/cmdb/ci", json={"name": "filter-cred-1", "ci_type": "credential"})

    resp = await client.get("/ops/cmdb/ci?ci_type=cert")
    assert resp.status_code == 200

    data = resp.json()
    # Filter to only our test certs (there might be other certs from previous tests)
    test_certs = [ci for ci in data if ci["name"].startswith("filter-cert")]
    assert all(ci["ci_type"] == "cert" for ci in test_certs)
    assert len(test_certs) == 2
    # Verify all returned items are certs
    assert all(ci["ci_type"] == "cert" for ci in data)


@pytest.mark.asyncio
async def test_get_expiring_cis(client):
    """Test getting expiring CIs."""
    # Register CI expiring in 5 days
    future_5 = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    await client.post("/ops/cmdb/ci", json={"name": "expiring-soon", "ci_type": "cert", "expires_at": future_5})

    # Register CI expiring in 60 days
    future_60 = (datetime.now(UTC) + timedelta(days=60)).isoformat()
    await client.post("/ops/cmdb/ci", json={"name": "expiring-later", "ci_type": "cert", "expires_at": future_60})

    # Get CIs expiring in 30 days
    resp = await client.get("/ops/cmdb/ci/expiring?days=30")
    assert resp.status_code == 200

    data = resp.json()
    assert len(data["expiring_in_7_days"]) == 1
    assert data["expiring_in_7_days"][0]["name"] == "expiring-soon"
    assert len(data["expiring_in_30_days"]) == 0


@pytest.mark.asyncio
async def test_get_expiring_cis_already_expired(client):
    """Test getting already expired CIs."""
    # Register expired CI
    past_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    await client.post("/ops/cmdb/ci", json={"name": "expired-cert", "ci_type": "cert", "expires_at": past_date})

    resp = await client.get("/ops/cmdb/ci/expiring?days=30")
    assert resp.status_code == 200

    data = resp.json()
    assert len(data["already_expired"]) == 1
    assert data["already_expired"][0]["name"] == "expired-cert"


@pytest.mark.asyncio
async def test_invalid_ci_type(client):
    """Test that invalid CI types are rejected."""
    ci_data = {"name": "invalid-ci", "ci_type": "not_a_valid_type"}

    resp = await client.post("/ops/cmdb/ci", json=ci_data)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_operational_status(client):
    """Test that invalid operational statuses are rejected."""
    ci_data = {"name": "invalid-status", "ci_type": "cert", "operational_status": "not_valid"}

    resp = await client.post("/ops/cmdb/ci", json=ci_data)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ci_with_parent(client):
    """Test registering CI with parent relationship."""
    # Register parent CI
    await client.post("/ops/cmdb/ci", json={"name": "parent-zone", "ci_type": "zone"})

    # Register child CI
    await client.post("/ops/cmdb/ci", json={"name": "child-record", "ci_type": "record", "parent_ci": "parent-zone"})

    # Get child CI
    resp = await client.get("/ops/cmdb/ci/child-record")
    assert resp.status_code == 200

    data = resp.json()
    assert data["parent_ci"] == "parent-zone"
