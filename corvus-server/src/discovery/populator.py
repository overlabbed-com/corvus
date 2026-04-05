"""Graph populator — merges discovery results into Neo4j.

Takes declared and optionally inspected DiscoveryResult objects, MERGEs nodes
and edges into the graph with provenance tracking. Uses batched Cypher
operations for performance.
"""

import logging
from datetime import UTC, datetime

from src.discovery.declared import DiscoveryResult
from src.graph import graph_session

logger = logging.getLogger(__name__)


async def populate_graph(
    declared: DiscoveryResult,
    inspected: DiscoveryResult | None = None,
    observed: DiscoveryResult | None = None,
) -> dict:
    """Populate the Neo4j graph from discovery results.

    Args:
        declared: Services and edges from compose file parsing.
        inspected: Optional runtime state from admin-api.
        observed: Optional network observation data (Layer 2).

    Returns:
        Stats dict: {services, edges, hosts, gpus, networks, drift_count, observed_edges}
    """
    now = datetime.now(UTC).isoformat()

    # Build inspected lookup for drift detection and confidence upgrade
    inspected_by_name: dict[str, dict] = {}
    if inspected:
        for svc in inspected.services:
            inspected_by_name[svc["name"]] = svc

    drift_count = 0
    stats = {
        "services": 0,
        "edges": 0,
        "hosts": 0,
        "gpus": 0,
        "networks": 0,
        "drift_count": 0,
    }

    async with graph_session() as session:
        # --- Hosts ---
        if declared.hosts:
            await session.run(
                """
                UNWIND $hosts AS h
                MERGE (host:Host {name: h.name})
                SET host.ip = h.ip,
                    host.role = h.role,
                    host.last_updated = $now
                """,
                hosts=declared.hosts,
                now=now,
            )
            stats["hosts"] = len(declared.hosts)

        # --- GPUs ---
        if declared.gpus:
            await session.run(
                """
                UNWIND $gpus AS g
                MERGE (gpu:GPU {host: g.host, index: g.index})
                SET gpu.model = g.model,
                    gpu.vram_gb = g.vram_gb,
                    gpu.last_updated = $now
                WITH gpu, g
                MATCH (h:Host {name: g.host})
                MERGE (gpu)-[:INSTALLED_ON]->(h)
                """,
                gpus=declared.gpus,
                now=now,
            )
            stats["gpus"] = len(declared.gpus)

        # --- Networks ---
        if declared.networks:
            await session.run(
                """
                UNWIND $networks AS n
                MERGE (net:Network {name: n.name})
                SET net.last_updated = $now
                """,
                networks=declared.networks,
                now=now,
            )
            stats["networks"] = len(declared.networks)

        # --- Services ---
        for svc in declared.services:
            drift_detected = False
            drift_fields: list[str] = []
            runtime_image = None
            runtime_healthcheck = None

            declared_image = svc.get("image", "")
            declared_healthcheck = svc.get("healthcheck", False)

            # Check for drift against inspected data
            if svc["name"] in inspected_by_name:
                runtime = inspected_by_name[svc["name"]]
                runtime_image = runtime.get("image", "")
                # admin-api returns "health" field; non-empty means healthcheck exists
                runtime_healthcheck = bool(runtime.get("health", ""))

                # Image drift
                if runtime_image and declared_image and runtime_image != declared_image:
                    drift_detected = True
                    drift_fields.append("image")
                    logger.info(
                        "Drift: %s image declared=%s runtime=%s",
                        svc["name"],
                        declared_image,
                        runtime_image,
                    )

                # Healthcheck drift: compose declares one but runtime doesn't have it
                # (stale container created before healthcheck was added)
                if declared_healthcheck and not runtime_healthcheck:
                    drift_detected = True
                    drift_fields.append("healthcheck")
                    logger.info(
                        "Drift: %s healthcheck declared=%s runtime=%s",
                        svc["name"],
                        declared_healthcheck,
                        runtime_healthcheck,
                    )

                if drift_detected:
                    drift_count += 1

            await session.run(
                """
                MERGE (s:Service {name: $name})
                SET s.host = $host,
                    s.declared_image = $declared_image,
                    s.runtime_image = $runtime_image,
                    s.image = $declared_image,
                    s.declared_healthcheck = $declared_healthcheck,
                    s.runtime_healthcheck = $runtime_healthcheck,
                    s.healthcheck = $declared_healthcheck,
                    s.service_type = $service_type,
                    s.stack = $stack,
                    s.drift_detected = $drift_detected,
                    s.drift_fields = $drift_fields,
                    s.last_updated = $now
                """,
                name=svc["name"],
                host=svc.get("host"),
                declared_image=declared_image,
                runtime_image=runtime_image,
                declared_healthcheck=declared_healthcheck,
                runtime_healthcheck=runtime_healthcheck,
                service_type=svc.get("service_type", "container"),
                stack=svc.get("stack", ""),
                drift_detected=drift_detected,
                drift_fields=drift_fields,
                now=now,
            )

            # RUNS_ON edge to host
            if svc.get("host"):
                await session.run(
                    """
                    MATCH (s:Service {name: $name})
                    MATCH (h:Host {name: $host})
                    MERGE (s)-[:RUNS_ON]->(h)
                    """,
                    name=svc["name"],
                    host=svc["host"],
                )

            # USES_GPU edges
            for gpu_idx in svc.get("gpu_indexes", []):
                await session.run(
                    """
                    MATCH (s:Service {name: $name})
                    MATCH (g:GPU {host: $host, index: $gpu_index})
                    MERGE (s)-[:USES_GPU]->(g)
                    """,
                    name=svc["name"],
                    host=svc.get("host", ""),
                    gpu_index=gpu_idx,
                )

        stats["services"] = len(declared.services)

        # --- Edges ---
        edge_count = 0
        for edge in declared.edges:
            if edge["type"] == "DEPENDS_ON":
                # Determine confidence: upgrade if confirmed by inspected layer
                confidence = edge.get("confidence", 0.7)
                layers = [edge.get("layer", "declared")]

                if inspected and edge["source"] in inspected_by_name and edge["target"] in inspected_by_name:
                    confidence = 0.95
                    if "inspected" not in layers:
                        layers.append("inspected")

                await session.run(
                    """
                    MATCH (src:Service {name: $source})
                    MATCH (tgt:Service {name: $target})
                    MERGE (src)-[r:DEPENDS_ON]->(tgt)
                    ON CREATE SET r.first_discovered = $now
                    SET r.layers = $layers,
                        r.confidence = $confidence,
                        r.last_confirmed = $now
                    """,
                    source=edge["source"],
                    target=edge["target"],
                    layers=layers,
                    confidence=confidence,
                    now=now,
                )
                edge_count += 1

            elif edge["type"] == "CONNECTS_TO":
                await session.run(
                    """
                    MATCH (src:Service {name: $source})
                    MATCH (net:Network {name: $target})
                    MERGE (src)-[r:CONNECTS_TO]->(net)
                    ON CREATE SET r.first_discovered = $now
                    SET r.layers = $layers,
                        r.last_confirmed = $now
                    """,
                    source=edge["source"],
                    target=edge["target"],
                    layers=[edge.get("layer", "declared")],
                    now=now,
                )
                edge_count += 1

        stats["edges"] = edge_count
        stats["drift_count"] = drift_count

        # --- Observed Edges (Layer 2) ---
        observed_edge_count = 0
        if observed:
            for edge in observed.edges:
                if edge.get("type") == "OBSERVED_CONNECTION":
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
                    observed_edge_count += 1

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

        stats["observed_edges"] = observed_edge_count

    logger.info(
        "Graph populated: %d services, %d edges (%d observed), %d hosts, %d gpus, %d drift",
        stats["services"],
        stats["edges"],
        observed_edge_count,
        stats["hosts"],
        stats["gpus"],
        stats["drift_count"],
    )

    return stats
