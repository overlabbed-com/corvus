"""Graph query API endpoints.

Provides blast radius analysis, dependency chain traversal, expiry queries,
GPU correlation, and general graph statistics via Neo4j Cypher.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from src.graph import (
    attempt_recovery,
    enter_safe_mode,
    graph_available,
    graph_health,
    graph_session,
    get_safe_mode_state,
)
from src.middleware.auth import AuthContext, get_auth

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_graph():
    """Raise 503 if graph database is not connected."""
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")


@router.get("/blast-radius/{service}")
async def blast_radius(service: str, auth: AuthContext = Depends(get_auth)):
    """Find all services that would break if the given service goes down.

    Traverses DEPENDS_ON edges inward (services that depend on this one),
    recursively up to 10 hops.
    """
    _require_graph()

    async with graph_session() as session:
        # Verify service exists
        r = await session.run(
            "MATCH (s:Service {name: $name}) RETURN s.name AS name",
            name=service,
        )
        if not await r.single():
            raise HTTPException(status_code=404, detail=f"Service '{service}' not found")

        # Traverse inward: who depends on this service?
        r = await session.run(
            """
            MATCH (target:Service {name: $name})
            MATCH path = (affected:Service)-[:DEPENDS_ON*1..5]->(target)
            RETURN DISTINCT affected.name AS name,
                   affected.host AS host,
                   affected.stack AS stack,
                   length(path) AS distance
            ORDER BY distance, name
            """,
            name=service,
        )
        affected = [
            {
                "name": rec["name"],
                "host": rec["host"],
                "stack": rec["stack"],
                "distance": rec["distance"],
            }
            async for rec in r
        ]

    return {
        "service": service,
        "affected_count": len(affected),
        "affected": affected,
    }


@router.get("/dependency-chain/{service}")
async def dependency_chain(service: str, auth: AuthContext = Depends(get_auth)):
    """Trace the full upstream dependency chain for a service.

    Traverses DEPENDS_ON edges outward (what this service depends on),
    recursively up to 10 hops.
    """
    _require_graph()

    async with graph_session() as session:
        r = await session.run(
            "MATCH (s:Service {name: $name}) RETURN s.name AS name",
            name=service,
        )
        if not await r.single():
            raise HTTPException(status_code=404, detail=f"Service '{service}' not found")

        r = await session.run(
            """
            MATCH (origin:Service {name: $name})
            MATCH path = (origin)-[:DEPENDS_ON*1..5]->(upstream:Service)
            RETURN DISTINCT upstream.name AS name,
                   upstream.host AS host,
                   upstream.stack AS stack,
                   length(path) AS distance
            ORDER BY distance, name
            """,
            name=service,
        )
        upstream = [
            {
                "name": rec["name"],
                "host": rec["host"],
                "stack": rec["stack"],
                "distance": rec["distance"],
            }
            async for rec in r
        ]

    return {
        "service": service,
        "upstream_count": len(upstream),
        "upstream": upstream,
    }


@router.get("/expiring")
async def expiring_items(
    days: int = Query(default=30, ge=1, le=365),
    auth: AuthContext = Depends(get_auth),
):
    """Find CIs with properties.expires_at within N days."""
    _require_graph()

    cutoff = (datetime.now(UTC) + timedelta(days=days)).isoformat()

    async with graph_session() as session:
        r = await session.run(
            """
            MATCH (c:CI)
            WHERE c.expires_at IS NOT NULL AND c.expires_at <= $cutoff
            RETURN c.type AS type, c.name AS name, c.service AS service,
                   c.expires_at AS expires_at
            ORDER BY c.expires_at
            """,
            cutoff=cutoff,
        )
        expiring = [
            {
                "type": rec["type"],
                "name": rec["name"],
                "service": rec["service"],
                "expires_at": rec["expires_at"],
            }
            async for rec in r
        ]

    return {
        "days": days,
        "cutoff": cutoff,
        "count": len(expiring),
        "expiring": expiring,
    }


@router.get("/correlated/{host}/{gpu_index}")
async def correlated_gpu_services(
    host: str,
    gpu_index: int,
    auth: AuthContext = Depends(get_auth),
):
    """Find all services sharing a specific GPU."""
    _require_graph()

    async with graph_session() as session:
        r = await session.run(
            """
            MATCH (g:GPU {host: $host, index: $gpu_index})
            MATCH (s:Service)-[:USES_GPU]->(g)
            RETURN s.name AS name, s.host AS host, s.stack AS stack, s.image AS image
            ORDER BY s.name
            """,
            host=host,
            gpu_index=gpu_index,
        )
        services = [
            {
                "name": rec["name"],
                "host": rec["host"],
                "stack": rec["stack"],
                "image": rec["image"],
            }
            async for rec in r
        ]

    return {
        "host": host,
        "gpu_index": gpu_index,
        "service_count": len(services),
        "services": services,
    }


@router.get("/services")
async def list_services(auth: AuthContext = Depends(get_auth)):
    """List all Service nodes with relationship summary."""
    _require_graph()

    async with graph_session() as session:
        r = await session.run(
            """
            MATCH (s:Service)
            OPTIONAL MATCH (s)-[:RUNS_ON]->(h:Host)
            OPTIONAL MATCH (s)-[:USES_GPU]->(g:GPU)
            OPTIONAL MATCH (s)-[dep:DEPENDS_ON]->(:Service)
            OPTIONAL MATCH (:Service)-[rdep:DEPENDS_ON]->(s)
            RETURN s.name AS name,
                   s.host AS host,
                   s.stack AS stack,
                   s.image AS image,
                   s.healthcheck AS healthcheck,
                   s.drift_detected AS drift_detected,
                   h.name AS host_node,
                   collect(DISTINCT g.index) AS gpu_indexes,
                   count(DISTINCT dep) AS depends_on_count,
                   count(DISTINCT rdep) AS depended_by_count
            ORDER BY s.name
            """
        )
        services = [
            {
                "name": rec["name"],
                "host": rec["host"],
                "stack": rec["stack"],
                "image": rec["image"],
                "healthcheck": rec["healthcheck"],
                "drift_detected": rec["drift_detected"],
                "gpu_indexes": rec["gpu_indexes"],
                "depends_on_count": rec["depends_on_count"],
                "depended_by_count": rec["depended_by_count"],
            }
            async for rec in r
        ]

    return {"count": len(services), "services": services}


@router.get("/drift")
async def get_config_drift(auth: AuthContext = Depends(get_auth)):
    """Find services where running config diverges from declared compose state.

    Detects stale containers that need force-recreate — e.g., a healthcheck
    added to compose but missing from the running container because it was
    created before the healthcheck was defined.
    """
    _require_graph()

    async with graph_session() as session:
        result = await session.run(
            """
            MATCH (s:Service)
            WHERE s.drift_detected = true
               OR (s.declared_image IS NOT NULL AND s.runtime_image IS NOT NULL
                   AND s.declared_image <> s.runtime_image)
               OR (s.declared_healthcheck IS NOT NULL AND s.runtime_healthcheck IS NOT NULL
                   AND s.declared_healthcheck <> s.runtime_healthcheck)
            RETURN s.name AS name,
                   s.host AS host,
                   s.stack AS stack,
                   s.declared_image AS declared_image,
                   s.runtime_image AS runtime_image,
                   s.declared_healthcheck AS declared_healthcheck,
                   s.runtime_healthcheck AS runtime_healthcheck,
                   s.drift_detected AS drift_detected,
                   s.drift_fields AS drift_fields
            ORDER BY s.name
            """
        )
        drifted = [dict(rec) async for rec in result]

    return {"drift_count": len(drifted), "services": drifted}


@router.get("/drift/{service}")
async def get_service_drift(service: str, auth: AuthContext = Depends(get_auth)):
    """Detailed drift report for a single service.

    Compares all declared fields against runtime fields and reports
    which specific properties have drifted.
    """
    _require_graph()

    async with graph_session() as session:
        result = await session.run(
            """
            MATCH (s:Service {name: $name})
            RETURN s.name AS name,
                   s.host AS host,
                   s.stack AS stack,
                   s.declared_image AS declared_image,
                   s.runtime_image AS runtime_image,
                   s.declared_healthcheck AS declared_healthcheck,
                   s.runtime_healthcheck AS runtime_healthcheck,
                   s.drift_detected AS drift_detected,
                   s.drift_fields AS drift_fields,
                   s.last_updated AS last_updated
            """,
            name=service,
        )
        rec = await result.single()

    if not rec:
        raise HTTPException(status_code=404, detail=f"Service '{service}' not found")

    data = dict(rec)

    # Build field-level comparison
    comparisons = []
    for field in ["image", "healthcheck"]:
        declared_val = data.get(f"declared_{field}")
        runtime_val = data.get(f"runtime_{field}")
        if declared_val is not None and runtime_val is not None:
            comparisons.append(
                {
                    "field": field,
                    "declared": declared_val,
                    "runtime": runtime_val,
                    "match": declared_val == runtime_val,
                }
            )

    data["comparisons"] = comparisons
    return data


@router.get("/stats")
async def graph_stats(auth: AuthContext = Depends(get_auth)):
    """Return node counts by label and edge counts by type."""
    _require_graph()

    async with graph_session() as session:
        node_counts = {}
        for label in ["Service", "Host", "GPU", "Network", "CI", "Incident"]:
            r = await session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            rec = await r.single()
            if rec:
                node_counts[label] = rec["cnt"]

        edge_counts = {}
        for rel_type in [
            "DEPENDS_ON",
            "RUNS_ON",
            "USES_GPU",
            "CONNECTS_TO",
            "INSTALLED_ON",
            "INFERRED_DEPENDENCY",
            "HAS_CI",
            "FEEDS",
        ]:
            r = await session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt")
            rec = await r.single()
            if rec:
                edge_counts[rel_type] = rec["cnt"]

    return {
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "total_nodes": sum(node_counts.values()),
        "total_edges": sum(edge_counts.values()),
    }


@router.get("/safe-mode")
async def get_safe_mode(auth: AuthContext = Depends(get_auth)):
    """Get current safe mode state and health metrics."""
    return {
        "safe_mode": get_safe_mode_state(),
        "health": graph_health(),
    }


@router.post("/safe-mode/enter")
async def force_safe_mode(auth: AuthContext = Depends(get_auth)):
    """Manually enter safe mode — all graph queries will be rejected.

    Use this to immediately stop all graph traffic during emergencies.
    """
    enter_safe_mode()
    logger.warning("Safe mode manually entered via API")
    return {
        "status": "safe_mode_entered",
        "state": get_safe_mode_state(),
    }


@router.post("/safe-mode/recover")
async def attempt_safe_mode_recovery(auth: AuthContext = Depends(get_auth)):
    """Attempt to recover from safe mode.

    Recovery is only attempted if the cooldown period has elapsed.
    Returns whether recovery was attempted and current state.
    """
    attempted = attempt_recovery()
    return {
        "recovery_attempted": attempted,
        "state": get_safe_mode_state(),
        "health": graph_health(),
        "message": (
            "Recovery initiated"
            if attempted
            else "Still in cooldown — try again later"
        ),
    }
