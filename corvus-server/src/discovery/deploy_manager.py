"""Deploy failure analysis and drift detection.

Integrates GitHub Actions deploy workflows with Corvus triage.
Detects deploy failure patterns and compares declared vs running state.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from src.database import get_db
from src.graph import graph_available, graph_session

logger = logging.getLogger(__name__)


class DeployStatus(StrEnum):
    """Deployment status values."""

    SUCCESS = "success"
    FAILURE = "failure"
    IN_PROGRESS = "in_progress"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class FailureDiagnosis(StrEnum):
    """Deploy failure diagnosis types."""

    RESOURCE_EXHAUSTION = "resource_exhaustion"
    SLOW_STARTUP = "slow_startup"
    STALE_CONFIG = "stale_container_config"
    IMAGE_PULL_FAILURE = "image_pull_failure"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    HEALTHCHECK_MISMATCH = "healthcheck_mismatch"
    NETWORK_DRIFT = "network_drift"
    ENV_DRIFT = "env_drift"
    UNKNOWN = "unknown_deploy_failure"


@dataclass
class DeclaredConfig:
    """GitOps declared configuration for a service."""

    image: str
    healthcheck: str | None = None
    env_hash: str | None = None  # SHA256 of env var names
    networks: list[str] | None = None
    resources: dict[str, Any] | None = None
    depends_on: list[str] | None = None


@dataclass
class RunningConfig:
    """Running container configuration."""

    image: str
    healthcheck: str | None = None
    env_hash: str | None = None
    networks: list[str] | None = None
    resources: dict[str, Any] | None = None
    state: str = "running"
    health_status: str = "unknown"
    oom_killed: bool = False
    restart_count: int = 0


@dataclass
class DeployDiagnosis:
    """Diagnosis of deploy failure."""

    diagnosis: FailureDiagnosis
    confidence: float
    error_message: str | None = None
    remediation: list[str] | None = None
    root_cause_hint: str | None = None


@dataclass
class DriftReport:
    """Configuration drift report."""

    service_name: str
    has_drift: bool
    drift_fields: list[str]
    declared: DeclaredConfig | None = None
    running: RunningConfig | None = None
    severity: str = "low"  # low, medium, high


async def analyze_deploy_failure(
    service_name: str,
    error_message: str,
    workflow_logs: str | None = None,
) -> DeployDiagnosis:
    """Analyze deploy failure and return diagnosis.

    Args:
        service_name: Name of the failed service
        error_message: Error message from deploy
        workflow_logs: Full workflow logs for pattern matching

    Returns:
        DeployDiagnosis with root cause hypothesis and remediation
    """
    error_lower = error_message.lower()

    # Pattern: OOMKilled / memory exhaustion
    if "oomkilled" in error_lower or "out of memory" in error_lower or "memory" in error_lower:
        return DeployDiagnosis(
            diagnosis=FailureDiagnosis.RESOURCE_EXHAUSTION,
            confidence=0.9,
            error_message=error_message,
            remediation=[
                "Check container memory limits in compose file",
                "Review service memory usage trends",
                "Increase memory limits or optimize service memory usage",
                "Consider adding memory reservation",
            ],
            root_cause_hint="Service exceeded memory limits",
        )

    # Pattern: Healthcheck timeout / slow startup
    if any(term in error_lower for term in ["healthcheck", "timeout", "startup", "starting"]):
        return DeployDiagnosis(
            diagnosis=FailureDiagnosis.SLOW_STARTUP,
            confidence=0.85,
            error_message=error_message,
            remediation=[
                "Check service startup logs for errors",
                "Increase healthcheck timeout in compose file",
                "Optimize service initialization sequence",
                "Verify dependencies are ready before service starts",
            ],
            root_cause_hint="Service takes longer than expected to start",
        )

    # Pattern: Stale config / out of sync
    if any(term in error_lower for term in ["stale", "out of sync", "mismatch", "conflict"]):
        return DeployDiagnosis(
            diagnosis=FailureDiagnosis.STALE_CONFIG,
            confidence=0.9,
            error_message=error_message,
            remediation=[
                "Re-sync compose file from GitOps repository",
                "Clear container cache and volumes if needed",
                "Force redeploy with docker compose up --force-recreate",
                "Verify no manual changes to running containers",
            ],
            root_cause_hint="Running configuration differs from declared state",
        )

    # Pattern: Image pull failure
    if any(term in error_lower for term in ["image pull", "pull access", "not found", "manifest"]):
        return DeployDiagnosis(
            diagnosis=FailureDiagnosis.IMAGE_PULL_FAILURE,
            confidence=0.95,
            error_message=error_message,
            remediation=[
                "Verify image tag exists in registry",
                "Check registry credentials in compose file",
                "Verify network connectivity to registry",
                "Try pulling image manually to confirm",
            ],
            root_cause_hint="Cannot pull container image",
        )

    # Pattern: Dependency unavailable
    if any(term in error_lower for term in ["connection refused", "dependency", "upstream", "service unavailable"]):
        return DeployDiagnosis(
            diagnosis=FailureDiagnosis.DEPENDENCY_UNAVAILABLE,
            confidence=0.8,
            error_message=error_message,
            remediation=[
                "Check health of dependent services",
                "Verify dependency startup order in compose file",
                "Add healthcheck dependencies if missing",
                "Review network connectivity between services",
            ],
            root_cause_hint="Required dependency not ready or unhealthy",
        )

    # Check workflow logs for additional patterns
    if workflow_logs:
        if "oom" in workflow_logs.lower():
            return DeployDiagnosis(
                diagnosis=FailureDiagnosis.RESOURCE_EXHAUSTION,
                confidence=0.85,
                error_message=error_message,
                remediation=["Increase container memory/CPU limits"],
                root_cause_hint="OOM detected in logs",
            )

        has_health = "health" in workflow_logs.lower()
        has_fail_or_timeout = "fail" in workflow_logs.lower() or "timeout" in workflow_logs.lower()
        if has_health and has_fail_or_timeout:
            return DeployDiagnosis(
                diagnosis=FailureDiagnosis.SLOW_STARTUP,
                confidence=0.8,
                error_message=error_message,
                remediation=["Increase healthcheck timeout"],
                root_cause_hint="Healthcheck failures in logs",
            )

    # Default: unknown failure
    return DeployDiagnosis(
        diagnosis=FailureDiagnosis.UNKNOWN,
        confidence=0.3,
        error_message=error_message,
        remediation=["Manual investigation required", "Check service logs"],
        root_cause_hint="No clear pattern detected",
    )


async def check_drift(
    service_name: str,
    declared: DeclaredConfig | None = None,
    running: RunningConfig | None = None,
) -> DriftReport:
    """Compare declared vs running state and detect drift.

    Args:
        service_name: Service to check
        declared: Declared config (if None, fetch from CMDB)
        running: Running config (if None, inspect container)

    Returns:
        DriftReport with detected differences
    """
    drift_fields = []

    # Fetch declared state if not provided
    if declared is None:
        declared = await _get_declared_state(service_name)

    # Fetch running state if not provided
    if running is None:
        running = await _get_running_state(service_name)

    if not declared or not running:
        return DriftReport(
            service_name=service_name,
            has_drift=False,
            drift_fields=[],
            declared=declared,
            running=running,
            severity="low",
        )

    # Compare image
    if declared.image != running.image:
        drift_fields.append("image")

    # Compare healthcheck
    if declared.healthcheck != running.healthcheck:
        drift_fields.append("healthcheck")

    # Compare env hash
    if declared.env_hash != running.env_hash:
        drift_fields.append("env_vars")

    # Compare networks
    if set(declared.networks or []) != set(running.networks or []):
        drift_fields.append("networks")

    # Compare resources
    if declared.resources != running.resources:
        drift_fields.append("resources")

    has_drift = len(drift_fields) > 0

    # Determine severity
    if "image" in drift_fields or "healthcheck" in drift_fields or len(drift_fields) >= 3:
        severity = "high"
    elif len(drift_fields) >= 2:
        severity = "medium"
    else:
        severity = "low"

    return DriftReport(
        service_name=service_name,
        has_drift=has_drift,
        drift_fields=drift_fields,
        declared=declared,
        running=running,
        severity=severity,
    )


async def register_declared_state(
    service_name: str,
    declared: DeclaredConfig,
) -> None:
    """Register declared state from GitOps in CMDB.

    Args:
        service_name: Service name
        declared: Declared configuration from compose file
    """
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()

        # Serialize networks and resources
        networks_json = json.dumps(declared.networks) if declared.networks else None
        json.dumps(declared.resources) if declared.resources else None

        # Update CMDB with declared state
        await db.execute(
            """UPDATE ops_cmdb SET
               declared_image = ?,
               declared_healthcheck = ?,
               declared_env_hash = ?,
               declared_networks = ?,
               last_declared_at = ?
               WHERE name = ?""",
            (
                declared.image,
                declared.healthcheck,
                declared.env_hash,
                networks_json,
                now,
                service_name,
            ),
        )

        # Also update in Neo4j if available
        if graph_available():
            async with graph_session() as session:
                await session.run(
                    """
                    MATCH (s:Service {name: $service_name})
                    SET s.declared_image = $image,
                        s.declared_healthcheck = $healthcheck,
                        s.declared_env_hash = $env_hash,
                        s.declared_networks = $networks,
                        s.last_declared_at = $updated_at
                    """,
                    service_name=service_name,
                    image=declared.image,
                    healthcheck=declared.healthcheck,
                    env_hash=declared.env_hash,
                    networks=networks_json,
                    updated_at=now,
                )

        await db.commit()
        logger.info(f"Registered declared state for {service_name}")

    finally:
        await db.close()


async def record_deploy_attempt(
    service_name: str,
    status: DeployStatus,
    workflow_run_id: int | None = None,
    error: str | None = None,
) -> None:
    """Record deploy attempt in CMDB.

    Args:
        service_name: Service name
        status: Deploy status
        workflow_run_id: GitHub Actions workflow run ID
        error: Error message if failed
    """
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()

        await db.execute(
            """UPDATE ops_cmdb SET
               last_deploy_attempt = ?,
               last_deploy_status = ?,
               last_deploy_error = ?
               WHERE name = ?""",
            (now, status.value, error, service_name),
        )

        await db.commit()

    finally:
        await db.close()


async def _get_declared_state(service_name: str) -> DeclaredConfig | None:
    """Get declared state from CMDB."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT declared_image, declared_healthcheck, declared_env_hash, "
            "declared_networks FROM ops_cmdb WHERE name = ?",
            (service_name,),
        )
        row = await cursor.fetchone()

        if not row or not row["declared_image"]:
            return None

        networks = json.loads(row["declared_networks"]) if row["declared_networks"] else None

        return DeclaredConfig(
            image=row["declared_image"],
            healthcheck=row["declared_healthcheck"],
            env_hash=row["declared_env_hash"],
            networks=networks,
        )
    finally:
        await db.close()


async def _get_running_state(service_name: str) -> RunningConfig | None:
    """Get running state by inspecting container.

    Note: This requires SSH access to Docker host.
    For now, returns None - to be implemented with Docker client.
    """
    # TODO: Implement Docker container inspection
    # This will need SSH access to the Docker host
    # or a Docker socket mount
    return None


def compute_env_hash(env_vars: dict[str, str]) -> str:
    """Compute hash of environment variable names (not values).

    Args:
        env_vars: Environment variables dict

    Returns:
        SHA256 hash of sorted env var names
    """
    sorted_names = sorted(env_vars.keys())
    return hashlib.sha256(json.dumps(sorted_names).encode()).hexdigest()
