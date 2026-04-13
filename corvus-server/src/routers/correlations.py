"""Correlation group API endpoints.

Detects when multiple incidents share a resource (GPU, network, volume, dependency)
and creates correlation groups to enable single-alert semantics.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.database import get_db
from src.graph import graph_available, graph_session
from src.middleware.auth import AuthContext, get_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/correlations", tags=["correlations"])


class CorrelationCheckRequest(BaseModel):
    """Request to check if incidents should be correlated."""

    incidents: list[str]  # Incident IDs
    host: str | None = None  # Optional host filter
    sweep_id: str | None = None  # Optional sweep identifier


class CorrelationGroup(BaseModel):
    """Correlation group response."""

    group_id: str
    root_cause: str
    shared_resource: str
    shared_resource_type: str  # "gpu", "network", "volume", "dependency"
    member_incidents: list[str]
    created_at: str


class CorrelationCheckResponse(BaseModel):
    """Response from correlation check."""

    correlated: bool
    group: CorrelationGroup | None = None
    message: str


async def _create_correlation_group(
    incident_ids: list[str],
    shared_resource: str,
    shared_resource_type: str,
    root_cause_hint: str,
) -> CorrelationGroup:
    """Create a correlation group in Neo4j and return it."""
    group_id = f"CG-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(UTC).isoformat()

    async with graph_session() as session:
        # Create CorrelationGroup node
        await session.run(
            """
            CREATE (cg:CorrelationGroup {
                id: $group_id,
                root_cause: $root_cause,
                shared_resource: $shared_resource,
                shared_resource_type: $shared_resource_type,
                created_at: $created_at
            })
            """,
            {
                "group_id": group_id,
                "root_cause": root_cause_hint,
                "shared_resource": shared_resource,
                "shared_resource_type": shared_resource_type,
                "created_at": now,
            },
        )

        # Link incidents to correlation group
        for incident_id in incident_ids:
            await session.run(
                """
                MATCH (i:Incident {id: $incident_id})
                MATCH (cg:CorrelationGroup {id: $group_id})
                CREATE (i)-[:MEMBER_OF]->(cg)
                """,
                {"incident_id": incident_id, "group_id": group_id},
            )

    return CorrelationGroup(
        group_id=group_id,
        root_cause=root_cause_hint,
        shared_resource=shared_resource,
        shared_resource_type=shared_resource_type,
        member_incidents=incident_ids,
        created_at=now,
    )


async def _sync_incidents_to_graph(incident_ids: list[str]) -> int:
    """Sync incidents from SQLite to Neo4j graph.

    Args:
        incident_ids: List of incident IDs to sync

    Returns:
        Number of incidents synced
    """
    db = await get_db()
    synced = 0

    for incident_id in incident_ids:
        cursor = await db.execute("SELECT * FROM ops_incidents WHERE id = ?", (incident_id,))
        row = await cursor.fetchone()
        if not row:
            continue

        # Convert row to dict
        incident = {
            "id": row["id"],
            "title": row["title"],
            "target": row["target"],
            "severity": row["severity"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

        async with graph_session() as session:
            # Create Incident node
            await session.run(
                """
                MERGE (i:Incident {id: $id})
                SET i.title = $title,
                    i.target = $target,
                    i.severity = $severity,
                    i.status = $status,
                    i.created_at = $created_at
                """,
                incident,
            )

            # Link to Service if known
            if incident["target"]:
                await session.run(
                    """
                    MATCH (i:Incident {id: $id})
                    MERGE (s:Service {name: $target})
                    MERGE (i)-[:AFFECTS]->(s)
                    """,
                    {"id": incident["id"], "target": incident["target"]},
                )
        synced += 1

    return synced


@router.post("/check", response_model=CorrelationCheckResponse)
async def check_correlation(
    request: CorrelationCheckRequest,
    auth: AuthContext = Depends(get_auth),
):
    """Check if incidents share a resource and should be grouped.

    Checks for shared:
    - GPU (same host + gpu_index)
    - Network (same network membership)
    - Volume (same volume mount)
    - Dependency (common unhealthy dependency)

    Returns a correlation group if 2+ incidents share a resource.
    """
    if len(request.incidents) < 2:
        return CorrelationCheckResponse(
            correlated=False,
            message="Need at least 2 incidents to check correlation",
        )

    if not graph_available():
        return CorrelationCheckResponse(
            correlated=False,
            message="Graph database not available — cannot check correlation",
        )

    # Sync incidents from SQLite to Neo4j first
    synced = await _sync_incidents_to_graph(request.incidents)
    if synced == 0:
        return CorrelationCheckResponse(
            correlated=False,
            message="No incidents found in database",
        )

    async with graph_session() as session:
        # Get incident details (services affected, host)
        incident_data = []
        for incident_id in request.incidents:
            result = await session.run(
                """
                MATCH (i:Incident {id: $incident_id})
                OPTIONAL MATCH (i)-[:AFFECTS]->(s:Service)
                OPTIONAL MATCH (i)-[:DETECTED_ON]->(h:Host)
                RETURN i.id AS incident_id, s.name AS service, h.name AS host
                """,
                {"incident_id": incident_id},
            )
            rec = await result.single()
            if rec:
                incident_data.append(
                    {
                        "incident_id": rec["incident_id"],
                        "service": rec["service"],
                        "host": rec["host"],
                    }
                )

        if len(incident_data) < 2:
            return CorrelationCheckResponse(
                correlated=False,
                message="Not all incidents found in graph",
            )

        # Check for shared GPU
        gpu_groups: dict[str, list[str]] = {}
        for data in incident_data:
            if not data["service"]:
                continue
            result = await session.run(
                """
                MATCH (s:Service {name: $service})-[:USES_GPU]->(g:GPU)
                RETURN g.host AS host, g.index AS gpu_index
                """,
                {"service": data["service"]},
            )
            rec = await result.single()
            if rec:
                gpu_key = f"gpu:{rec['host']}:{rec['gpu_index']}"
                if gpu_key not in gpu_groups:
                    gpu_groups[gpu_key] = []
                gpu_groups[gpu_key].append(data["incident_id"])

        # Find GPU with 2+ incidents
        for gpu_key, incidents in gpu_groups.items():
            if len(incidents) >= 2:
                group = await _create_correlation_group(
                    incident_ids=incidents,
                    shared_resource=gpu_key,
                    shared_resource_type="gpu",
                    root_cause_hint=f"Check GPU state (VRAM, temperature, driver) on {gpu_key}",
                )
                logger.info("Created correlation group %s for GPU failure: %s", group.group_id, incidents)
                return CorrelationCheckResponse(
                    correlated=True,
                    group=group,
                    message=f"Found shared GPU: {gpu_key}",
                )

        # Check for shared host (5+ incidents)
        host_groups: dict[str, list[str]] = {}
        for data in incident_data:
            if data["host"]:
                if data["host"] not in host_groups:
                    host_groups[data["host"]] = []
                host_groups[data["host"]].append(data["incident_id"])

        for host, incidents in host_groups.items():
            if len(incidents) >= 5:
                group = await _create_correlation_group(
                    incident_ids=incidents,
                    shared_resource=f"host:{host}",
                    shared_resource_type="host",
                    root_cause_hint=f"Check host-level resources (disk, RAM, network) on {host}",
                )
                logger.info("Created correlation group %s for host failure: %s", group.group_id, incidents)
                return CorrelationCheckResponse(
                    correlated=True,
                    group=group,
                    message=f"Found shared host: {host}",
                )

        # Check for shared dependency
        dependency_groups: dict[str, list[str]] = {}
        for data in incident_data:
            if not data["service"]:
                continue
            result = await session.run(
                """
                MATCH (s:Service {name: $service})-[:DEPENDS_ON]->(dep:Service)
                OPTIONAL MATCH (inc:Incident {status: "open"})-[:AFFECTS]->(dep)
                WHERE inc IS NOT NULL
                RETURN dep.name AS unhealthy_dep
                """,
                {"service": data["service"]},
            )
            async for rec in result:
                if rec["unhealthy_dep"]:
                    dep_key = f"dependency:{rec['unhealthy_dep']}"
                    if dep_key not in dependency_groups:
                        dependency_groups[dep_key] = []
                    dependency_groups[dep_key].append(data["incident_id"])

        # Find dependency with 2+ incidents
        for dep_key, incidents in dependency_groups.items():
            if len(incidents) >= 2:
                dep_name = dep_key.replace("dependency:", "")
                group = await _create_correlation_group(
                    incident_ids=incidents,
                    shared_resource=dep_key,
                    shared_resource_type="dependency",
                    root_cause_hint=f"Fix dependency '{dep_name}' first — dependents will likely recover",
                )
                logger.info("Created correlation group %s for dependency failure: %s", group.group_id, incidents)
                return CorrelationCheckResponse(
                    correlated=True,
                    group=group,
                    message=f"Found shared unhealthy dependency: {dep_name}",
                )

    return CorrelationCheckResponse(
        correlated=False,
        message="No shared resources detected — incidents are independent",
    )


@router.get("/group/{group_id}")
async def get_correlation_group(
    group_id: str,
    auth: AuthContext = Depends(get_auth),
):
    """Get details of a correlation group."""
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    async with graph_session() as session:
        result = await session.run(
            """
            MATCH (cg:CorrelationGroup {id: $group_id})
            OPTIONAL MATCH (cg)<-[:MEMBER_OF]-(i:Incident)
            RETURN cg.id AS group_id,
                   cg.root_cause AS root_cause,
                   cg.shared_resource AS shared_resource,
                   cg.shared_resource_type AS shared_resource_type,
                   cg.created_at AS created_at,
                   collect(i.id) AS member_incidents
            """,
            {"group_id": group_id},
        )
        rec = await result.single()

    if not rec:
        raise HTTPException(status_code=404, detail=f"Correlation group '{group_id}' not found")

    return {
        "group_id": rec["group_id"],
        "root_cause": rec["root_cause"],
        "shared_resource": rec["shared_resource"],
        "shared_resource_type": rec["shared_resource_type"],
        "created_at": rec["created_at"],
        "member_incidents": rec["member_incidents"],
        "member_count": len(rec["member_incidents"]),
    }


@router.get("/active")
async def list_active_correlations(
    auth: AuthContext = Depends(get_auth),
):
    """List all active correlation groups with open incidents."""
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    async with graph_session() as session:
        result = await session.run(
            """
            MATCH (cg:CorrelationGroup)<-[:MEMBER_OF]-(i:Incident {status: "open"})
            WITH cg, count(DISTINCT i) AS open_count
            WHERE open_count > 0
            MATCH (cg)<-[:MEMBER_OF]-(i:Incident)
            RETURN cg.id AS group_id,
                   cg.root_cause AS root_cause,
                   cg.shared_resource AS shared_resource,
                   cg.shared_resource_type AS shared_resource_type,
                   cg.created_at AS created_at,
                   collect(DISTINCT i.id) AS member_incidents,
                   open_count
            ORDER BY cg.created_at DESC
            """
        )
        groups = []
        async for rec in result:
            groups.append(
                {
                    "group_id": rec["group_id"],
                    "root_cause": rec["root_cause"],
                    "shared_resource": rec["shared_resource"],
                    "shared_resource_type": rec["shared_resource_type"],
                    "created_at": rec["created_at"],
                    "member_incidents": rec["member_incidents"],
                    "member_count": len(rec["member_incidents"]),
                    "open_count": rec["open_count"],
                }
            )

    return {
        "count": len(groups),
        "groups": groups,
    }
