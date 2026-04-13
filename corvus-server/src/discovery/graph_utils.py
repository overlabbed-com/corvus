"""Graph utility functions for triage enhancement.

Provides graph-based context for FMEA triage:
- Upstream/downstream dependency analysis
- Shared resource detection
- Health propagation analysis
"""

import logging
from typing import Any

from src.graph import graph_available, graph_session

logger = logging.getLogger(__name__)


async def get_upstream_dependencies(
    service_name: str,
    depth: int = 2,
) -> list[dict[str, Any]]:
    """Get upstream dependencies of a service.

    Args:
        service_name: Service to analyze
        depth: How many levels of dependencies to traverse

    Returns:
        List of dependency info with health status
    """
    if not graph_available():
        logger.warning("Neo4j not available, returning empty dependencies")
        return []

    try:
        async with graph_session() as session:
            # Build recursive query based on depth
            if depth == 1:
                query = """
                MATCH (s:Service {name: $service})-[:DEPENDS_ON]->(dep:Service)
                RETURN dep.name as name,
                       dep.service_type as type,
                       dep.critical as critical,
                       s.health_status as health
                """
            else:
                # For depth > 1, we need to traverse multiple levels
                query = """
                MATCH path = (s:Service {name: $service})-[:DEPENDS_ON*1..$depth]->(dep:Service)
                WITH DISTINCT dep, length(path) as level
                RETURN dep.name as name,
                       dep.service_type as type,
                       dep.critical as critical,
                       level
                ORDER BY level
                """

            result = await session.run(query, service=service_name, depth=depth)
            dependencies = []
            async for record in result:
                dependencies.append({
                    "name": record["name"],
                    "type": record.get("type"),
                    "critical": record.get("critical", False),
                    "depth": record.get("depth", 1),
                })

            return dependencies

    except Exception as e:
        logger.error(f"Failed to get upstream dependencies for {service_name}: {e}")
        return []


async def get_downstream_dependents(
    service_name: str,
    depth: int = 2,
) -> list[dict[str, Any]]:
    """Get services that depend on this service.

    Args:
        service_name: Service to analyze
        depth: How many levels to traverse

    Returns:
        List of dependent services
    """
    if not graph_available():
        return []

    try:
        async with graph_session() as session:
            query = """
            MATCH path = (dep:Service)-[:DEPENDS_ON*1..$depth]->(s:Service {name: $service})
            WITH DISTINCT dep, length(path) as level
            RETURN dep.name as name,
                   dep.service_type as type,
                   dep.critical as critical,
                   level
            ORDER BY level
            """

            result = await session.run(query, service=service_name, depth=depth)
            dependents = []
            async for record in result:
                dependents.append({
                    "name": record["name"],
                    "type": record.get("type"),
                    "critical": record.get("critical", False),
                    "depth": record.get("depth", 1),
                })

            return dependents

    except Exception as e:
        logger.error(f"Failed to get downstream dependents for {service_name}: {e}")
        return []


async def find_shared_resources(
    service_names: list[str],
    resource_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Find resources shared by multiple services.

    Args:
        service_names: Services to analyze
        resource_types: Types of resources to look for (gpu, network, volume, etc.)

    Returns:
        List of shared resources with service memberships
    """
    if not graph_available():
        return []

    if not resource_types:
        resource_types = ["gpu", "network", "volume", "dependency"]

    try:
        async with graph_session() as session:
            shared_resources = []

            for resource_type in resource_types:
                # Find resources used by multiple services
                query = """
                MATCH (s:Service)-[:USES]->(r)
                WHERE r.ci_type = $resource_type OR labels(r) CONTAINS $resource_type
                WITH r, collect(s.name) as services
                WHERE size(services) > 1
                RETURN r.name as resource,
                       r.ci_type as type,
                       services
                """

                result = await session.run(query, resource_type=resource_type)
                async for record in result:
                    shared_resources.append({
                        "resource": record["resource"],
                        "type": record["type"],
                        "services": record["services"],
                        "service_count": len(record["services"]),
                    })

            return shared_resources

    except Exception as e:
        logger.error(f"Failed to find shared resources: {e}")
        return []


async def check_graph_health(
    service_names: list[str],
) -> dict[str, str]:
    """Check health status of services and their dependencies.

    Args:
        service_names: Services to check

    Returns:
        Dict mapping service name to health status
    """
    if not graph_available():
        return dict.fromkeys(service_names, "unknown")

    try:
        async with graph_session() as session:
            # Query health for all services at once
            placeholders = ",".join(["$" + f"svc{i}" for i in range(len(service_names))])
            query = f"""
            MATCH (s:Service)
            WHERE s.name IN [{placeholders}]
            RETURN s.name as name, s.health_status as health
            """

            params = {f"svc{i}": name for i, name in enumerate(service_names)}
            result = await session.run(query, **params)

            health_map = {}
            async for record in result:
                health_map[record["name"]] = record.get("health", "unknown")

            # Fill in missing services as unknown
            for name in service_names:
                if name not in health_map:
                    health_map[name] = "unknown"

            return health_map

    except Exception as e:
        logger.error(f"Failed to check graph health: {e}")
        return dict.fromkeys(service_names, "unknown")


async def get_root_cause_hypothesis(
    service_name: str,
    incident_details: dict[str, Any],
) -> dict[str, Any]:
    """Generate root cause hypothesis using graph context.

    Args:
        service_name: Failing service
        incident_details: Incident information

    Returns:
        Root cause hypothesis with confidence
    """
    if not graph_available():
        return {
            "hypothesis": "Unable to analyze - graph unavailable",
            "confidence": 0.0,
            "evidence": [],
        }

    try:
        # Get upstream dependencies
        upstream = await get_upstream_dependencies(service_name, depth=2)

        # Check health of upstream services
        upstream_names = [d["name"] for d in upstream]
        health_map = await check_graph_health(upstream_names)

        # Find unhealthy upstream services
        unhealthy_upstream = [
            {"name": d["name"], "type": d["type"], "critical": d["critical"]}
            for d in upstream
            if health_map.get(d["name"]) in ["unhealthy", "degraded"]
        ]

        # Find shared resources
        shared = await find_shared_resources([service_name] + upstream_names)
        problematic_shared = [
            s for s in shared
            if any(health_map.get(svc) != "healthy" for svc in s["services"])
        ]

        # Generate hypothesis
        if unhealthy_upstream:
            critical_unhealthy = [u for u in unhealthy_upstream if u["critical"]]
            if critical_unhealthy:
                return {
                    "hypothesis": f"Critical upstream dependency failure: {critical_unhealthy[0]['name']}",
                    "confidence": 0.85,
                    "evidence": [
                        f"Unhealthy critical dependency: {critical_unhealthy[0]['name']}",
                        f"Total unhealthy upstream: {len(unhealthy_upstream)}",
                    ],
                    "recommended_action": f"Check and fix {critical_unhealthy[0]['name']} first",
                }
            else:
                return {
                    "hypothesis": f"Upstream dependency failure: {unhealthy_upstream[0]['name']}",
                    "confidence": 0.75,
                    "evidence": [
                        f"Unhealthy dependency: {unhealthy_upstream[0]['name']}",
                        f"Total unhealthy upstream: {len(unhealthy_upstream)}",
                    ],
                    "recommended_action": f"Check {unhealthy_upstream[0]['name']} health",
                }

        if problematic_shared:
            return {
                "hypothesis": f"Shared resource contention: {problematic_shared[0]['resource']}",
                "confidence": 0.70,
                "evidence": [
                    f"Shared resource with unhealthy services: {problematic_shared[0]['resource']}",
                    f"Affected services: {', '.join(problematic_shared[0]['services'])}",
                ],
                "recommended_action": f"Check resource {problematic_shared[0]['resource']} state",
            }

        return {
            "hypothesis": "No clear graph-based root cause detected",
            "confidence": 0.30,
            "evidence": [
                f"Checked {len(upstream)} upstream dependencies",
                f"Checked {len(shared)} shared resources",
                "All upstream services appear healthy",
            ],
            "recommended_action": "Manual investigation required",
        }

    except Exception as e:
        logger.error(f"Failed to generate root cause hypothesis: {e}")
        return {
            "hypothesis": "Error generating hypothesis",
            "confidence": 0.0,
            "evidence": [str(e)],
            "recommended_action": "Try again or investigate manually",
        }
