"""Service discovery API endpoints.

Orchestrates declared (compose) and inspected (runtime) discovery layers,
populates the Neo4j graph, and reports coverage gaps.

Layers 4-6 add reported (agent self-registration), inferred (temporal
correlation), and elicited (knowledge capture) discovery.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.discovery.declared import parse_compose_dir
from src.discovery.deploy_manager import analyze_deploy_failure
from src.discovery.inspected import inspect_containers
from src.discovery.observed import (
    RawConnection,
    build_ip_map,
    connections_to_discovery_result,
    parse_conntrack,
    parse_tetragon_events,
    resolve_connections,
    summarize_connections,
)
from src.discovery.populator import populate_graph
from src.graph import graph_available, graph_session
from src.middleware.auth import AuthContext, get_auth

logger = logging.getLogger(__name__)

router = APIRouter()


class BootstrapRequest(BaseModel):
    compose_dir: str
    admin_api_url: str = ""
    admin_api_token: str = ""


class BootstrapResponse(BaseModel):
    services: int
    edges: int
    hosts: int
    gpus: int
    networks: int
    drift_count: int
    duration_ms: int


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=200)
async def bootstrap_discovery(
    req: BootstrapRequest,
    auth: AuthContext = Depends(get_auth),
):
    """Run declared + inspected discovery and populate the graph.

    Parses all docker-compose.yml files under compose_dir, optionally queries
    admin-api for runtime state, and merges everything into Neo4j.
    """
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    import time

    start = time.monotonic()

    # Layer 1: Declared (compose files)
    declared = parse_compose_dir(req.compose_dir)
    logger.info(
        "Declared discovery: %d services, %d edges",
        len(declared.services),
        len(declared.edges),
    )

    # Layer 3: Inspected (runtime)
    inspected = None
    if req.admin_api_url:
        inspected = await inspect_containers(req.admin_api_url, req.admin_api_token)
        logger.info("Inspected discovery: %d services", len(inspected.services))

    # Populate graph
    stats = await populate_graph(declared, inspected)

    duration_ms = round((time.monotonic() - start) * 1000)

    return BootstrapResponse(
        services=stats["services"],
        edges=stats["edges"],
        hosts=stats["hosts"],
        gpus=stats["gpus"],
        networks=stats.get("networks", 0),
        drift_count=stats.get("drift_count", 0),
        duration_ms=duration_ms,
    )


@router.get("/status")
async def discovery_status(auth: AuthContext = Depends(get_auth)):
    """Return last scan time per layer and node/edge counts."""
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    async with graph_session() as session:
        # Count nodes by label
        result = await session.run(
            """
            CALL db.labels() YIELD label
            CALL apoc.cypher.run('MATCH (n:`' + label + '`) RETURN count(n) AS cnt', {})
            YIELD value
            RETURN label, value.cnt AS count
            """
        )
        # Fallback: count nodes without APOC
        node_counts = {}
        try:
            records = await result.data()
            for rec in records:
                node_counts[rec["label"]] = rec["count"]
        except Exception:
            # APOC not available — count manually for known labels
            for label in ["Service", "Host", "GPU", "Network", "CI", "Incident"]:
                r = await session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
                rec = await r.single()
                if rec:
                    node_counts[label] = rec["cnt"]

        # Count edges by type
        edge_counts = {}
        for rel_type in [
            "DEPENDS_ON",
            "RUNS_ON",
            "USES_GPU",
            "CONNECTS_TO",
            "INSTALLED_ON",
            "OBSERVED_CONNECTION",
        ]:
            r = await session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt")
            rec = await r.single()
            if rec:
                edge_counts[rel_type] = rec["cnt"]

    return {
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/coverage")
async def discovery_coverage(auth: AuthContext = Depends(get_auth)):
    """Return services with no deps, CIs with no parent, and stale edges."""
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    async with graph_session() as session:
        # Services with zero outgoing DEPENDS_ON
        r = await session.run(
            """
            MATCH (s:Service)
            WHERE NOT (s)-[:DEPENDS_ON]->()
            RETURN s.name AS name
            ORDER BY s.name
            """
        )
        no_deps = [rec["name"] async for rec in r]

        # Services with zero incoming DEPENDS_ON (nothing depends on them)
        r = await session.run(
            """
            MATCH (s:Service)
            WHERE NOT ()-[:DEPENDS_ON]->(s)
            RETURN s.name AS name
            ORDER BY s.name
            """
        )
        no_dependents = [rec["name"] async for rec in r]

        # Services not connected to any host
        r = await session.run(
            """
            MATCH (s:Service)
            WHERE NOT (s)-[:RUNS_ON]->()
            RETURN s.name AS name
            ORDER BY s.name
            """
        )
        no_host = [rec["name"] async for rec in r]

    return {
        "no_dependencies": no_deps,
        "no_dependents": no_dependents,
        "no_host": no_host,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# Layer 2: Observed (Network Traffic)
# ---------------------------------------------------------------------------


class ConnectionTuple(BaseModel):
    src_ip: str
    src_port: int = 0
    dst_ip: str
    dst_port: int = 0
    protocol: str = "tcp"
    host: str = ""
    timestamp: str = ""


class ConnectionsRequest(BaseModel):
    format: str = "tuples"  # "tuples", "conntrack", "tetragon"
    host: str = ""
    connections: list[ConnectionTuple] = Field(default_factory=list)
    raw_text: str = ""  # For conntrack format
    events: list[dict] = Field(default_factory=list)  # For Tetragon format
    admin_api_url: str = ""
    admin_api_token: str = ""


@router.post("/connections", status_code=201)
async def ingest_connections(
    req: ConnectionsRequest,
    auth: AuthContext = Depends(get_auth),
):
    """Ingest observed TCP connections from collectors (Layer 2: Observed).

    Accepts data in three formats:
    - tuples: Pre-parsed connection tuples [{src_ip, dst_ip, dst_port, ...}]
    - conntrack: Raw conntrack -L output (raw_text field)
    - tetragon: Tetragon kprobe TCP connect events (events field)

    Resolves IPs to container names using admin-api, deduplicates, and
    writes OBSERVED_CONNECTION edges to the graph.
    """
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    # Parse connections based on format
    raw_connections: list[RawConnection] = []

    if req.format == "conntrack" and req.raw_text:
        raw_connections = parse_conntrack(req.raw_text, host=req.host)
    elif req.format == "tetragon" and req.events:
        raw_connections = parse_tetragon_events(req.events, host=req.host)
    else:
        # Default: pre-parsed tuples
        for ct in req.connections:
            raw_connections.append(
                RawConnection(
                    src_ip=ct.src_ip,
                    src_port=ct.src_port,
                    dst_ip=ct.dst_ip,
                    dst_port=ct.dst_port,
                    protocol=ct.protocol,
                    host=ct.host or req.host,
                    timestamp=ct.timestamp,
                )
            )

    if not raw_connections:
        return {
            "accepted": True,
            "resolved": 0,
            "unresolved": 0,
            "edges_created": 0,
            "message": "No connections to process",
        }

    # Build IP map from admin-api
    admin_url = req.admin_api_url
    admin_token = req.admin_api_token

    if not admin_url:
        # Try environment
        import os

        admin_url = os.getenv("ADMIN_API_URL", "")
        admin_token = admin_token or os.getenv("ADMIN_API_TOKEN", "")

    ip_map: dict[str, str] = {}
    if admin_url:
        ip_map = await build_ip_map(admin_url, admin_token)

    # Resolve connections
    observation = resolve_connections(raw_connections, ip_map)

    if not observation.connections:
        return {
            "accepted": True,
            "resolved": 0,
            "unresolved": len(observation.unresolved),
            "edges_created": 0,
            "ip_map_size": observation.ip_map_size,
            "message": "No connections resolved to known containers",
        }

    # Convert to DiscoveryResult and populate graph
    observed_result = connections_to_discovery_result(observation.connections)

    now = datetime.now(UTC).isoformat()
    edges_created = 0

    async with graph_session() as session:
        for edge in observed_result.edges:
            await session.run(
                """
                MATCH (src:Service {name: $source})
                MATCH (tgt:Service {name: $target})
                MERGE (src)-[r:OBSERVED_CONNECTION]->(tgt)
                ON CREATE SET r.first_observed = $now,
                              r.layers = ['observed']
                SET r.last_observed = $now,
                    r.confidence = 0.8,
                    r.dst_port = $dst_port,
                    r.protocol = $protocol,
                    r.observation_count = $count
                """,
                source=edge["source"],
                target=edge["target"],
                dst_port=edge.get("dst_port", 0),
                protocol=edge.get("protocol", "tcp"),
                count=edge.get("count", 1),
                now=now,
            )
            edges_created += 1

            # Upgrade DEPENDS_ON confidence if observed confirms declared
            await session.run(
                """
                MATCH (src:Service {name: $source})-[r:DEPENDS_ON]->(tgt:Service {name: $target})
                SET r.confidence = CASE
                        WHEN r.confidence < 0.95 THEN 0.95
                        ELSE r.confidence
                    END,
                    r.layers = CASE
                        WHEN NOT 'observed' IN r.layers
                        THEN r.layers + 'observed'
                        ELSE r.layers
                    END,
                    r.last_confirmed = $now
                """,
                source=edge["source"],
                target=edge["target"],
                now=now,
            )

    summary = summarize_connections(observation.connections)

    logger.info(
        "Layer 2 observation: %d raw → %d resolved → %d edges, %d unresolved",
        len(raw_connections),
        len(observation.connections),
        edges_created,
        len(observation.unresolved),
    )

    return {
        "accepted": True,
        "resolved": len(observation.connections),
        "unresolved": len(observation.unresolved),
        "edges_created": edges_created,
        "ip_map_size": observation.ip_map_size,
        "summary": summary,
        "timestamp": now,
    }


@router.get("/connections")
async def list_observed_connections(auth: AuthContext = Depends(get_auth)):
    """List all observed service-to-service connections from the graph."""
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    async with graph_session() as session:
        r = await session.run(
            """
            MATCH (src:Service)-[r:OBSERVED_CONNECTION]->(tgt:Service)
            RETURN src.name AS source, tgt.name AS target,
                   r.dst_port AS port, r.protocol AS protocol,
                   r.observation_count AS count,
                   r.confidence AS confidence,
                   r.first_observed AS first_observed,
                   r.last_observed AS last_observed
            ORDER BY r.observation_count DESC
            """
        )
        connections = [
            {
                "source": rec["source"],
                "target": rec["target"],
                "port": rec.get("port"),
                "protocol": rec.get("protocol"),
                "count": rec.get("count"),
                "confidence": rec.get("confidence"),
                "first_observed": rec.get("first_observed"),
                "last_observed": rec.get("last_observed"),
            }
            async for rec in r
        ]

    return {
        "count": len(connections),
        "connections": connections,
    }


@router.post("/collect", status_code=200)
async def trigger_collection(auth: AuthContext = Depends(get_auth)):
    """Trigger an on-demand Layer 2 collection sweep.

    Uses the Corvus-native collector to query Docker hosts directly:
    - Docker network inspect → IP-to-container mapping
    - Docker exec /proc/net/tcp → active TCP connections per container
    - Resolution through the IP map → service-to-service edges

    Writes OBSERVED_CONNECTION edges to the graph.
    """
    from src.discovery.collector import DOCKER_HOSTS, run_collection

    if not DOCKER_HOSTS:
        return {
            "status": "skipped",
            "message": "No Docker hosts configured (set CORVUS_DOCKER_HOSTS)",
        }

    result = await run_collection()

    # Write to graph if we have edges
    if result.get("edges", 0) > 0 and graph_available():
        from src.discovery.declared import DiscoveryResult

        await populate_graph(
            DiscoveryResult(),  # empty declared
            observed=result["discovery_result"],
        )
        logger.info("Wrote %d observed edges to graph", result["edges"])

    return {
        "status": "completed",
        "hosts": result.get("hosts", 0),
        "ip_map_size": result.get("ip_map_size", 0),
        "raw_connections": result.get("raw_connections", 0),
        "resolved": result.get("resolved", 0),
        "unresolved": result.get("unresolved", 0),
        "edges": result.get("edges", 0),
        "summary": result.get("summary"),
    }


# ---------------------------------------------------------------------------
# Layer 4: Reported (Agent / Self-Registration)
# ---------------------------------------------------------------------------


class ReportedService(BaseModel):
    name: str
    host: str | None = None
    service_type: str | None = "container"


class ReportedEdge(BaseModel):
    source: str
    target: str
    type: str = "DEPENDS_ON"
    confidence: float = 0.8


class ReportedCI(BaseModel):
    type: str
    name: str
    service: str
    properties: dict = Field(default_factory=dict)


class ReportRequest(BaseModel):
    reporter: str
    layer: str = "reported"
    services: list[ReportedService] = Field(default_factory=list)
    edges: list[ReportedEdge] = Field(default_factory=list)
    cis: list[ReportedCI] = Field(default_factory=list)


@router.post("/report", status_code=201)
async def report_discovery(
    req: ReportRequest,
    auth: AuthContext = Depends(get_auth),
):
    """Accept CI and dependency reports from agents (Layer 4: Reported).

    Agents and services self-report their configuration items and dependencies.
    Written to Neo4j with layer='reported' provenance.
    """
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    now = datetime.now(UTC).isoformat()
    stats = {"services": 0, "edges": 0, "cis": 0}

    async with graph_session() as session:
        # Merge reported services
        for svc in req.services:
            await session.run(
                """
                MERGE (s:Service {name: $name})
                SET s.last_reported = $now,
                    s.reported_by = $reporter
                WITH s
                FOREACH (_ IN CASE WHEN $host IS NOT NULL THEN [1] ELSE [] END |
                    SET s.host = $host
                )
                FOREACH (_ IN CASE WHEN $service_type IS NOT NULL THEN [1] ELSE [] END |
                    SET s.service_type = $service_type
                )
                """,
                name=svc.name,
                host=svc.host,
                service_type=svc.service_type,
                now=now,
                reporter=req.reporter,
            )
            # RUNS_ON edge if host specified
            if svc.host:
                await session.run(
                    """
                    MATCH (s:Service {name: $name})
                    MATCH (h:Host {name: $host})
                    MERGE (s)-[:RUNS_ON]->(h)
                    """,
                    name=svc.name,
                    host=svc.host,
                )
            stats["services"] += 1

        # Merge reported edges
        for edge in req.edges:
            rel_type = edge.type.upper().replace(" ", "_")
            if rel_type == "DEPENDS_ON":
                await session.run(
                    """
                    MATCH (src:Service {name: $source})
                    MATCH (tgt:Service {name: $target})
                    MERGE (src)-[r:DEPENDS_ON]->(tgt)
                    ON CREATE SET r.first_discovered = $now,
                                  r.layers = ['reported']
                    ON MATCH SET r.layers = CASE
                        WHEN NOT 'reported' IN r.layers
                        THEN r.layers + 'reported'
                        ELSE r.layers
                    END
                    SET r.confidence = CASE
                            WHEN r.confidence IS NULL OR $confidence > r.confidence
                            THEN $confidence ELSE r.confidence
                        END,
                        r.last_confirmed = $now,
                        r.reported_by = $reporter
                    """,
                    source=edge.source,
                    target=edge.target,
                    confidence=edge.confidence,
                    now=now,
                    reporter=req.reporter,
                )
            elif rel_type == "FEEDS":
                await session.run(
                    """
                    MATCH (src:Service {name: $source})
                    MATCH (tgt:Service {name: $target})
                    MERGE (src)-[r:FEEDS]->(tgt)
                    ON CREATE SET r.first_discovered = $now,
                                  r.layers = ['reported']
                    SET r.confidence = $confidence,
                        r.last_confirmed = $now,
                        r.reported_by = $reporter
                    """,
                    source=edge.source,
                    target=edge.target,
                    confidence=edge.confidence,
                    now=now,
                    reporter=req.reporter,
                )
            stats["edges"] += 1

        # Merge reported CIs
        for ci in req.cis:
            props = ci.properties or {}
            await session.run(
                """
                MERGE (c:CI {type: $type, name: $name})
                SET c.service = $service,
                    c.layer = 'reported',
                    c.reported_by = $reporter,
                    c.last_reported = $now,
                    c.expires_at = $expires_at,
                    c.provider = $provider
                WITH c
                MATCH (s:Service {name: $service})
                MERGE (s)-[:HAS_CI]->(c)
                """,
                type=ci.type,
                name=ci.name,
                service=ci.service,
                reporter=req.reporter,
                now=now,
                expires_at=props.get("expires_at"),
                provider=props.get("provider"),
            )
            stats["cis"] += 1

    logger.info(
        "Layer 4 report from %s: %d services, %d edges, %d CIs",
        req.reporter,
        stats["services"],
        stats["edges"],
        stats["cis"],
    )

    return {
        "accepted": True,
        "reporter": req.reporter,
        "stats": stats,
        "timestamp": now,
    }


# ---------------------------------------------------------------------------
# Layer 5: Inferred (Historical / Temporal Correlation)
# ---------------------------------------------------------------------------


@router.post("/infer")
async def run_inference(auth: AuthContext = Depends(get_auth)):
    """Trigger temporal correlation analysis (Layer 5: Inferred).

    Mines the operational graph for implicit dependencies based on incident
    co-occurrence and change cascades. Creates INFERRED_DEPENDENCY edges with
    low confidence that go to the suggestions queue for human validation.
    """
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    now = datetime.now(UTC).isoformat()
    inferred_edges = 0

    async with graph_session() as session:
        # Check if we have any incidents at all
        r = await session.run("MATCH (i:Incident) RETURN count(i) AS cnt")
        rec = await r.single()
        incident_count = rec["cnt"] if rec else 0

        if incident_count < 3:
            return {
                "inferred_edges": 0,
                "incident_count": incident_count,
                "message": "Insufficient operational history — need at least 3 incidents for correlation",
                "timestamp": now,
            }

        # 1. Incident co-occurrence: services failing within 15 min, 3+ times
        r = await session.run(
            """
            MATCH (i1:Incident)-[:AFFECTS]->(s1:Service)
            MATCH (i2:Incident)-[:AFFECTS]->(s2:Service)
            WHERE s1 <> s2
              AND s1.name < s2.name
              AND i1.created_at IS NOT NULL
              AND i2.created_at IS NOT NULL
              AND abs(duration.inSeconds(
                  datetime(i1.created_at),
                  datetime(i2.created_at)
              ).seconds) < 900
            WITH s1, s2, count(*) AS co_occurrences
            WHERE co_occurrences >= 3
            RETURN s1.name AS service_a, s2.name AS service_b, co_occurrences
            """
        )
        co_occurrence_results = await r.data()

        for row in co_occurrence_results:
            confidence = min(0.3 + (row["co_occurrences"] * 0.1), 0.6)
            await session.run(
                """
                MATCH (s1:Service {name: $service_a})
                MATCH (s2:Service {name: $service_b})
                MERGE (s1)-[r:INFERRED_DEPENDENCY]->(s2)
                ON CREATE SET r.first_inferred = $now
                SET r.confidence = $confidence,
                    r.co_occurrences = $co_occurrences,
                    r.evidence = 'incident_co_occurrence',
                    r.last_inferred = $now
                """,
                service_a=row["service_a"],
                service_b=row["service_b"],
                confidence=confidence,
                co_occurrences=row["co_occurrences"],
                now=now,
            )
            inferred_edges += 1

        # 2. Change cascade: changes to A cause incidents on B within 24h
        r = await session.run(
            """
            MATCH (e:Event {type: 'change.completed'})-[:AFFECTS]->(s1:Service)
            MATCH (i:Incident)-[:AFFECTS]->(s2:Service)
            WHERE s1 <> s2
              AND e.created_at IS NOT NULL
              AND i.created_at IS NOT NULL
              AND datetime(i.created_at) > datetime(e.created_at)
              AND duration.inSeconds(
                  datetime(e.created_at),
                  datetime(i.created_at)
              ).seconds < 86400
            WITH s1, s2, count(*) AS cascade_count
            WHERE cascade_count >= 2
            RETURN s1.name AS changed_service,
                   s2.name AS affected_service,
                   cascade_count
            """
        )
        cascade_results = await r.data()

        for row in cascade_results:
            confidence = min(0.3 + (row["cascade_count"] * 0.15), 0.6)
            await session.run(
                """
                MATCH (s1:Service {name: $changed})
                MATCH (s2:Service {name: $affected})
                MERGE (s2)-[r:INFERRED_DEPENDENCY]->(s1)
                ON CREATE SET r.first_inferred = $now
                SET r.confidence = $confidence,
                    r.cascade_count = $cascade_count,
                    r.evidence = 'change_cascade',
                    r.last_inferred = $now
                """,
                changed=row["changed_service"],
                affected=row["affected_service"],
                confidence=confidence,
                cascade_count=row["cascade_count"],
                now=now,
            )
            inferred_edges += 1

    logger.info("Layer 5 inference: %d edges inferred", inferred_edges)

    return {
        "inferred_edges": inferred_edges,
        "incident_count": incident_count,
        "co_occurrence_pairs": len(co_occurrence_results),
        "cascade_pairs": len(cascade_results),
        "timestamp": now,
    }


@router.get("/suggestions")
async def list_suggestions(auth: AuthContext = Depends(get_auth)):
    """List inferred dependency edges awaiting human validation."""
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    async with graph_session() as session:
        r = await session.run(
            """
            MATCH (s1:Service)-[r:INFERRED_DEPENDENCY]->(s2:Service)
            WHERE r.validated IS NULL
            RETURN s1.name AS source, s2.name AS target,
                   r.confidence AS confidence, r.evidence AS evidence,
                   r.co_occurrences AS co_occurrences,
                   r.cascade_count AS cascade_count,
                   r.first_inferred AS first_inferred,
                   r.last_inferred AS last_inferred
            ORDER BY r.confidence DESC
            """
        )
        suggestions = [
            {
                "source": rec["source"],
                "target": rec["target"],
                "confidence": rec["confidence"],
                "evidence": rec["evidence"],
                "co_occurrences": rec.get("co_occurrences"),
                "cascade_count": rec.get("cascade_count"),
                "first_inferred": rec.get("first_inferred"),
                "last_inferred": rec.get("last_inferred"),
            }
            async for rec in r
        ]

    return {
        "count": len(suggestions),
        "suggestions": suggestions,
    }


class ValidateRequest(BaseModel):
    valid: bool
    notes: str = ""


@router.post("/suggestions/{source}/{target}/validate")
async def validate_suggestion(
    source: str,
    target: str,
    req: ValidateRequest,
    auth: AuthContext = Depends(get_auth),
):
    """Accept or reject an inferred dependency edge.

    If valid: upgrade to DEPENDS_ON with layers=['inferred','elicited'], confidence 0.9.
    If rejected: delete the INFERRED_DEPENDENCY edge.
    """
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    now = datetime.now(UTC).isoformat()

    async with graph_session() as session:
        # Verify the edge exists
        r = await session.run(
            """
            MATCH (s1:Service {name: $source})-[r:INFERRED_DEPENDENCY]->(s2:Service {name: $target})
            RETURN r.confidence AS confidence
            """,
            source=source,
            target=target,
        )
        rec = await r.single()
        if not rec:
            raise HTTPException(
                status_code=404,
                detail=f"No inferred dependency from '{source}' to '{target}'",
            )

        if req.valid:
            # Upgrade: create DEPENDS_ON and remove INFERRED_DEPENDENCY
            await session.run(
                """
                MATCH (s1:Service {name: $source})-[old:INFERRED_DEPENDENCY]->(s2:Service {name: $target})
                MERGE (s1)-[r:DEPENDS_ON]->(s2)
                ON CREATE SET r.first_discovered = old.first_inferred
                SET r.layers = ['inferred', 'elicited'],
                    r.confidence = 0.9,
                    r.validated_at = $now,
                    r.validation_notes = $notes,
                    r.last_confirmed = $now
                DELETE old
                """,
                source=source,
                target=target,
                now=now,
                notes=req.notes,
            )
            action = "upgraded"
        else:
            # Reject: delete the inferred edge
            await session.run(
                """
                MATCH (s1:Service {name: $source})-[r:INFERRED_DEPENDENCY]->(s2:Service {name: $target})
                DELETE r
                """,
                source=source,
                target=target,
            )
            action = "rejected"

    logger.info(
        "Suggestion %s -> %s %s (notes: %s)",
        source,
        target,
        action,
        req.notes,
    )

    return {
        "source": source,
        "target": target,
        "action": action,
        "timestamp": now,
    }


# ---------------------------------------------------------------------------
# Layer 6: Elicited (Knowledge Capture)
# ---------------------------------------------------------------------------


class KnowledgeRequest(BaseModel):
    source: str
    knowledge_type: str = "dependency"
    from_service: str
    to_service: str
    relationship: str = "DEPENDS_ON"
    notes: str = ""
    confidence: float = 0.95


@router.post("/knowledge", status_code=201)
async def report_knowledge(
    req: KnowledgeRequest,
    auth: AuthContext = Depends(get_auth),
):
    """Capture tribal knowledge as graph edges (Layer 6: Elicited).

    Accepts dependency knowledge from any source — typically surfaced during
    incident resolution or operational review. Creates edges with layer='elicited'
    and high confidence.
    """
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    now = datetime.now(UTC).isoformat()

    async with graph_session() as session:
        rel_type = req.relationship.upper().replace(" ", "_")

        if rel_type == "DEPENDS_ON":
            await session.run(
                """
                MATCH (src:Service {name: $from_svc})
                MATCH (tgt:Service {name: $to_svc})
                MERGE (src)-[r:DEPENDS_ON]->(tgt)
                ON CREATE SET r.first_discovered = $now,
                              r.layers = ['elicited']
                ON MATCH SET r.layers = CASE
                    WHEN NOT 'elicited' IN r.layers
                    THEN r.layers + 'elicited'
                    ELSE r.layers
                END
                SET r.confidence = CASE
                        WHEN r.confidence IS NULL OR $confidence > r.confidence
                        THEN $confidence ELSE r.confidence
                    END,
                    r.last_confirmed = $now,
                    r.elicited_by = $source,
                    r.elicited_notes = $notes
                """,
                from_svc=req.from_service,
                to_svc=req.to_service,
                confidence=req.confidence,
                source=req.source,
                notes=req.notes,
                now=now,
            )
        else:
            # Generic relationship type
            await session.run(
                f"""
                MATCH (src:Service {{name: $from_svc}})
                MATCH (tgt:Service {{name: $to_svc}})
                MERGE (src)-[r:{rel_type}]->(tgt)
                ON CREATE SET r.first_discovered = $now,
                              r.layers = ['elicited']
                SET r.confidence = $confidence,
                    r.last_confirmed = $now,
                    r.elicited_by = $source,
                    r.elicited_notes = $notes
                """,
                from_svc=req.from_service,
                to_svc=req.to_service,
                confidence=req.confidence,
                source=req.source,
                notes=req.notes,
                now=now,
            )

    logger.info(
        "Layer 6 knowledge: %s -> %s (%s) from %s",
        req.from_service,
        req.to_service,
        rel_type,
        req.source,
    )

    return {
        "accepted": True,
        "from_service": req.from_service,
        "to_service": req.to_service,
        "relationship": rel_type,
        "layer": "elicited",
        "confidence": req.confidence,
        "timestamp": now,
    }


@router.get("/knowledge")
async def list_knowledge(auth: AuthContext = Depends(get_auth)):
    """List all elicited knowledge entries (edges with 'elicited' in layers)."""
    if not graph_available():
        raise HTTPException(status_code=503, detail="Graph database not configured")

    async with graph_session() as session:
        r = await session.run(
            """
            MATCH (src:Service)-[r:DEPENDS_ON]->(tgt:Service)
            WHERE 'elicited' IN r.layers
            RETURN src.name AS from_service, tgt.name AS to_service,
                   r.confidence AS confidence, r.layers AS layers,
                   r.elicited_by AS source, r.elicited_notes AS notes,
                   r.first_discovered AS first_discovered,
                   r.last_confirmed AS last_confirmed
            ORDER BY r.last_confirmed DESC
            """
        )
        entries = [
            {
                "from_service": rec["from_service"],
                "to_service": rec["to_service"],
                "confidence": rec["confidence"],
                "layers": rec["layers"],
                "source": rec.get("source"),
                "notes": rec.get("notes"),
                "first_discovered": rec.get("first_discovered"),
                "last_confirmed": rec.get("last_confirmed"),
            }
            async for rec in r
        ]

    return {
        "count": len(entries),
        "entries": entries,
    }


class DeployAnalyzeRequest(BaseModel):
    service: str
    error: str
    workflow_logs: str | None = None


@router.post("/deploy/analyze")
async def analyze_deploy(
    req: DeployAnalyzeRequest,
    auth: AuthContext = Depends(get_auth),
):
    """Analyze a deploy failure and return diagnosis.
    
    Args:
        service: Name of the failed service
        error: Error message from deploy
        workflow_logs: Optional full workflow logs
        
    Returns:
        DeployDiagnosis with root cause and remediation
    """
    result = await analyze_deploy_failure(
        service_name=req.service,
        error_message=req.error,
        workflow_logs=req.workflow_logs,
    )
    return {
        "service": req.service,
        "diagnosis": result.diagnosis.value if hasattr(result.diagnosis, 'value') else result.diagnosis,
        "confidence": result.confidence,
        "error": result.error_message,
        "remediation": result.remediation,
        "root_cause_hint": result.root_cause_hint,
    }
