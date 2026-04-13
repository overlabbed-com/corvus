"""Tests for deploy failure analysis and drift detection."""

import pytest

from src.discovery.deploy_manager import (
    DeclaredConfig,
    DeployDiagnosis,
    FailureDiagnosis,
    analyze_deploy_failure,
    check_drift,
    compute_env_hash,
    record_deploy_attempt,
    register_declared_state,
)


@pytest.mark.asyncio
async def test_analyze_oom_failure():
    """Test OOM failure diagnosis."""
    diagnosis = await analyze_deploy_failure(
        service_name="test-service",
        error_message="Container OOMKilled: out of memory",
    )
    
    assert diagnosis.diagnosis == FailureDiagnosis.RESOURCE_EXHAUSTION
    assert diagnosis.confidence >= 0.9
    assert "memory" in " ".join(diagnosis.remediation or []).lower()


@pytest.mark.asyncio
async def test_analyze_healthcheck_timeout():
    """Test healthcheck timeout diagnosis."""
    diagnosis = await analyze_deploy_failure(
        service_name="test-service",
        error_message="Healthcheck timeout after 30s",
    )
    
    assert diagnosis.diagnosis == FailureDiagnosis.SLOW_STARTUP
    assert diagnosis.confidence >= 0.8
    assert any("timeout" in r.lower() for r in diagnosis.remediation or [])


@pytest.mark.asyncio
async def test_analyze_stale_config():
    """Test stale config diagnosis."""
    diagnosis = await analyze_deploy_failure(
        service_name="test-service",
        error_message="Configuration out of sync with GitOps",
    )
    
    assert diagnosis.diagnosis == FailureDiagnosis.STALE_CONFIG
    assert diagnosis.confidence >= 0.9


@pytest.mark.asyncio
async def test_analyze_image_pull_failure():
    """Test image pull failure diagnosis."""
    diagnosis = await analyze_deploy_failure(
        service_name="test-service",
        error_message="Failed to pull image: manifest not found",
    )
    
    assert diagnosis.diagnosis == FailureDiagnosis.IMAGE_PULL_FAILURE
    assert diagnosis.confidence >= 0.9


@pytest.mark.asyncio
async def test_analyze_dependency_unavailable():
    """Test dependency unavailable diagnosis."""
    diagnosis = await analyze_deploy_failure(
        service_name="test-service",
        error_message="Connection refused to upstream service",
    )
    
    assert diagnosis.diagnosis == FailureDiagnosis.DEPENDENCY_UNAVAILABLE
    assert diagnosis.confidence >= 0.8


@pytest.mark.asyncio
async def test_analyze_unknown_failure():
    """Test unknown failure falls back to default."""
    diagnosis = await analyze_deploy_failure(
        service_name="test-service",
        error_message="Some random error",
    )
    
    assert diagnosis.diagnosis == FailureDiagnosis.UNKNOWN
    assert diagnosis.confidence < 0.5


@pytest.mark.asyncio
async def test_compute_env_hash():
    """Test environment hash computation."""
    env1 = {"FOO": "bar", "BAZ": "qux"}
    env2 = {"BAZ": "different", "FOO": "value"}  # Same keys, different values
    
    hash1 = compute_env_hash(env1)
    hash2 = compute_env_hash(env2)
    
    # Hash should be same (only names matter, not values)
    assert hash1 == hash2
    
    # Hash should be deterministic
    assert compute_env_hash(env1) == hash1


@pytest.mark.asyncio
async def test_compute_env_hash_different_keys():
    """Test that different env var keys produce different hashes."""
    env1 = {"FOO": "bar"}
    env2 = {"BAR": "foo"}
    
    hash1 = compute_env_hash(env1)
    hash2 = compute_env_hash(env2)
    
    assert hash1 != hash2


@pytest.mark.asyncio
async def test_register_declared_state(client):
    """Test registering declared state in CMDB."""
    declared = DeclaredConfig(
        image="myimage:latest",
        healthcheck="curl -f http://localhost/health",
        env_hash="abc123",
        networks=["bridge", "custom"],
    )
    
    # First register the service
    await client.post(
        "/ops/cmdb/register",
        json={"name": "test-service", "host": "host1", "service_type": "utility"},
    )
    
    # Register declared state
    await register_declared_state("test-service", declared)
    
    # Verify it was stored
    resp = await client.get("/ops/cmdb/test-service")
    assert resp.status_code == 200
    
    # Note: The response doesn't include declared fields yet
    # This test mainly verifies no errors occur


@pytest.mark.asyncio
async def test_record_deploy_attempt(client):
    """Test recording deploy attempt."""
    # First register the service
    await client.post(
        "/ops/cmdb/register",
        json={"name": "test-service-2", "host": "host1", "service_type": "utility"},
    )
    
    # Record successful deploy
    from src.discovery.deploy_manager import DeployStatus
    
    await record_deploy_attempt(
        service_name="test-service-2",
        status=DeployStatus.SUCCESS,
        workflow_run_id=12345,
    )
    
    # Record failed deploy
    await record_deploy_attempt(
        service_name="test-service-2",
        status=DeployStatus.FAILURE,
        workflow_run_id=12346,
        error="Test error message",
    )
    
    # Verify no errors occurred
    assert True


@pytest.mark.asyncio
async def test_check_drift_no_declared():
    """Test drift check with no declared state."""
    report = await check_drift(service_name="non-existent-service")
    
    assert report.has_drift is False
    assert len(report.drift_fields) == 0


@pytest.mark.asyncio
async def test_check_drift_with_declared():
    """Test drift check with declared state."""
    declared = DeclaredConfig(
        image="myimage:v1",
        healthcheck="curl health",
        env_hash="abc123",
        networks=["bridge"],
    )
    
    # No running state available yet (not implemented)
    report = await check_drift(
        service_name="test-service-3",
        declared=declared,
        running=None,
    )
    
    # Should not have drift if running state unknown
    assert report.has_drift is False
