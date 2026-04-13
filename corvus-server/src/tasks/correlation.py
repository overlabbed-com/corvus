"""Background task for correlation group detection.

Runs after every health sweep to detect when multiple incidents share
a resource (GPU, host, dependency) and should be grouped.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from src.database import get_db
from src.graph import graph_available, graph_session
from src.routers.correlations import _create_correlation_group

logger = logging.getLogger(__name__)


async def sweep_for_correlations():
    """Run after every health sweep to detect correlation opportunities.

    This task:
    1. Finds open incidents from the last sweep (last 15 minutes)
    2. Groups them by shared GPU, host, or dependency
    3. Creates correlation groups for eligible clusters
    4. Logs correlation detection for audit
    """
    if not graph_available():
        logger.debug("Graph database not available — skipping correlation sweep")
        return

    logger.info("Starting correlation sweep")

    # Find open incidents from last 15 minutes
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT id, created_at
            FROM ops_incidents
            WHERE status = 'open'
              AND created_at > datetime('now', '-15 minutes')
            ORDER BY created_at
            """,
        )
        recent_incidents = await cursor.fetchall()
    finally:
        await db.close()

    if len(recent_incidents) < 2:
        logger.debug("Only %d recent incident — no correlation needed", len(recent_incidents))
        return

    incident_ids = [inc["id"] for inc in recent_incidents]
    logger.info("Found %d recent open incidents to check for correlation", len(incident_ids))

    # Check for correlations using graph queries
    async with graph_session() as session:
        # Group by GPU
        gpu_groups: dict[str, list[str]] = {}
        for incident_id in incident_ids:
            result = await session.run(
                """
                MATCH (i:Incident {id: $incident_id})-[:AFFECTS]->(s:Service)
                MATCH (s)-[:USES_GPU]->(g:GPU)
                RETURN g.host AS host, g.index AS gpu_index
                """,
                incident_id=incident_id,
            )
            rec = await result.single()
            if rec:
                gpu_key = f"gpu:{rec['host']}:{rec['gpu_index']}"
                if gpu_key not in gpu_groups:
                    gpu_groups[gpu_key] = []
                gpu_groups[gpu_key].append(incident_id)

        # Create correlation groups for GPUs with 2+ incidents
        for gpu_key, incidents in gpu_groups.items():
            if len(incidents) >= 2:
                # Check if already correlated
                existing = await session.run(
                    """
                    MATCH (cg:CorrelationGroup {shared_resource: $gpu_key})
                    OPTIONAL MATCH (cg)<-[:MEMBER_OF]-(i:Incident {status: "open"})
                    RETURN count(DISTINCT i) AS open_members
                    """,
                    gpu_key=gpu_key,
                )
                existing_rec = await existing.single()
                if existing_rec and existing_rec["open_members"] >= 2:
                    logger.debug("GPU %s already has correlation group", gpu_key)
                    continue

                group = await _create_correlation_group(
                    incident_ids=incidents,
                    shared_resource=gpu_key,
                    shared_resource_type="gpu",
                    root_cause_hint=f"Check GPU state (VRAM, temperature, driver) on {gpu_key}",
                )
                logger.info(
                    "Auto-created correlation group %s for GPU failure: %s",
                    group.group_id, incidents
                )

        # Group by host (5+ incidents threshold)
        host_groups: dict[str, list[str]] = {}
        for incident_id in incident_ids:
            result = await session.run(
                """
                MATCH (i:Incident {id: $incident_id})-[:DETECTED_ON]->(h:Host)
                RETURN h.name AS host
                """,
                incident_id=incident_id,
            )
            rec = await result.single()
            if rec:
                host = rec["host"]
                if host not in host_groups:
                    host_groups[host] = []
                host_groups[host].append(incident_id)

        # Create correlation groups for hosts with 5+ incidents
        for host, incidents in host_groups.items():
            if len(incidents) >= 5:
                # Check if already correlated
                existing = await session.run(
                    """
                    MATCH (cg:CorrelationGroup {shared_resource: $host_key})
                    OPTIONAL MATCH (cg)<-[:MEMBER_OF]-(i:Incident {status: "open"})
                    RETURN count(DISTINCT i) AS open_members
                    """,
                    host_key=f"host:{host}",
                )
                existing_rec = await existing.single()
                if existing_rec and existing_rec["open_members"] >= 5:
                    logger.debug("Host %s already has correlation group", host)
                    continue

                group = await _create_correlation_group(
                    incident_ids=incidents,
                    shared_resource=f"host:{host}",
                    shared_resource_type="host",
                    root_cause_hint=f"Check host-level resources (disk, RAM, network) on {host}",
                )
                logger.info(
                    "Auto-created correlation group %s for host failure: %s",
                    group.group_id, incidents
                )

        # Group by shared unhealthy dependency
        dependency_groups: dict[str, list[str]] = {}
        for incident_id in incident_ids:
            result = await session.run(
                """
                MATCH (i:Incident {id: $incident_id})-[:AFFECTS]->(s:Service)
                MATCH (s)-[:DEPENDS_ON]->(dep:Service)
                OPTIONAL MATCH (inc:Incident {status: "open"})-[:AFFECTS]->(dep)
                WHERE inc IS NOT NULL
                RETURN dep.name AS unhealthy_dep
                """,
                incident_id=incident_id,
            )
            async for rec in result:
                if rec["unhealthy_dep"]:
                    dep_key = f"dependency:{rec['unhealthy_dep']}"
                    if dep_key not in dependency_groups:
                        dependency_groups[dep_key] = []
                    dependency_groups[dep_key].append(incident_id)

        # Create correlation groups for dependencies with 2+ incidents
        for dep_key, incidents in dependency_groups.items():
            if len(incidents) >= 2:
                # Check if already correlated
                existing = await session.run(
                    """
                    MATCH (cg:CorrelationGroup {shared_resource: $dep_key})
                    OPTIONAL MATCH (cg)<-[:MEMBER_OF]-(i:Incident {status: "open"})
                    RETURN count(DISTINCT i) AS open_members
                    """,
                    dep_key=dep_key,
                )
                existing_rec = await existing.single()
                if existing_rec and existing_rec["open_members"] >= 2:
                    logger.debug("Dependency %s already has correlation group", dep_key)
                    continue

                dep_name = dep_key.replace("dependency:", "")
                group = await _create_correlation_group(
                    incident_ids=incidents,
                    shared_resource=dep_key,
                    shared_resource_type="dependency",
                    root_cause_hint=f"Fix dependency '{dep_name}' first — dependents will likely recover",
                )
                logger.info(
                    "Auto-created correlation group %s for dependency failure: %s",
                    group.group_id, incidents
                )

    logger.info("Correlation sweep completed")


async def run_correlation_sweep_loop():
    """Run correlation sweep every 5 minutes.

    This is the background task that periodically checks for correlation
    opportunities among open incidents.
    """
    logger.info("Starting correlation sweep loop (interval: 5 minutes)")
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes
            await sweep_for_correlations()
        except asyncio.CancelledError:
            logger.info("Correlation sweep loop cancelled")
            break
        except Exception:
            logger.exception("Error in correlation sweep loop")
