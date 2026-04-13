"""Graph-powered triage endpoints.

Enhanced FMEA triage using Neo4j graph context.
"""

import logging

from fastapi import APIRouter, HTTPException

from src.database import get_db
from src.discovery.graph_utils import (
    check_graph_health,
    find_shared_resources,
    get_downstream_dependents,
    get_root_cause_hypothesis,
    get_upstream_dependencies,
)
from src.graph import graph_available

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/triage", tags=["triage-graph"])


@router.post("/with-graph")
async def triage_with_graph(
    service_name: str,
    incident_title: str | None = None,
    incident_description: str | None = None,
):
    """Enhanced triage with graph context.

    Args:
        service_name: Service to triage
        incident_title: Optional incident title
        incident_description: Optional incident description

    Returns:
        Enhanced triage result with graph insights
    """
    if not graph_available():
        return {
            "service": service_name,
            "diagnosis": "graph_unavailable",
            "confidence": 0.0,
            "message": "Neo4j graph database not available",
            "recommendation": "Standard triage without graph context",
        }

    try:
        # Get graph context
        upstream = await get_upstream_dependencies(service_name, depth=2)
        downstream = await get_downstream_dependents(service_name, depth=2)
        shared = await find_shared_resources([service_name])

        # Check health of related services
        related_services = [service_name] + [u["name"] for u in upstream] + [d["name"] for d in downstream]
        health_map = await check_graph_health(related_services)

        # Generate root cause hypothesis
        incident_details = {
            "title": incident_title,
            "description": incident_description,
        }
        root_cause = await get_root_cause_hypothesis(service_name, incident_details)

        return {
            "service": service_name,
            "graph_available": True,
            "upstream_dependencies": upstream,
            "downstream_dependents": downstream,
            "shared_resources": shared,
            "health_status": health_map,
            "root_cause_hypothesis": root_cause,
            "recommendation": root_cause.get("recommended_action"),
            "confidence": root_cause.get("confidence", 0.0),
        }

    except Exception as e:
        logger.error(f"Graph-powered triage failed for {service_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Graph triage failed: {str(e)}") from None


@router.get("/{incident_id}/graph-context")
async def get_triage_graph_context(incident_id: str):
    """Get graph context used in triage for an incident.

    Args:
        incident_id: Incident ID

    Returns:
        Graph context snapshot
    """
    db = await get_db()
    try:
        # Get incident details
        cursor = await db.execute(
            "SELECT target, root_cause FROM ops_incidents WHERE id = ?",
            (incident_id,),
        )
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Incident not found")

        service_name = row["target"]

        # Re-fetch graph context
        upstream = await get_upstream_dependencies(service_name, depth=2)
        downstream = await get_downstream_dependents(service_name, depth=2)
        shared = await find_shared_resources([service_name])
        health_map = await check_graph_health([service_name] + [u["name"] for u in upstream])

        return {
            "incident_id": incident_id,
            "service": service_name,
            "upstream_dependencies": upstream,
            "downstream_dependents": downstream,
            "shared_resources": shared,
            "health_status": health_map,
            "original_root_cause": row["root_cause"],
        }

    finally:
        await db.close()


@router.post("/root-cause-analysis")
async def root_cause_analysis(
    service_name: str,
    error_message: str | None = None,
    affected_services: list[str] | None = None,
):
    """Graph-based root cause analysis.

    Args:
        service_name: Primary failing service
        error_message: Error message from logs
        affected_services: List of other affected services

    Returns:
        Root cause analysis with confidence and evidence
    """
    if not graph_available():
        return {
            "hypothesis": "Unable to analyze - graph unavailable",
            "confidence": 0.0,
            "evidence": ["Neo4j not available"],
            "recommended_action": "Manual investigation required",
        }

    try:
        # Include affected services in analysis
        services_to_analyze = [service_name]
        if affected_services:
            services_to_analyze.extend(affected_services)

        # Find shared resources among all affected services
        shared = await find_shared_resources(services_to_analyze)

        # Get upstream for primary service
        upstream = await get_upstream_dependencies(service_name, depth=3)
        upstream_names = [u["name"] for u in upstream]

        # Check health of all relevant services
        all_services = services_to_analyze + upstream_names
        health_map = await check_graph_health(all_services)

        # Find unhealthy upstream services
        unhealthy_upstream = [u for u in upstream if health_map.get(u["name"]) in ["unhealthy", "degraded"]]

        # Find critical unhealthy services
        critical_unhealthy = [u for u in unhealthy_upstream if u.get("critical")]

        # Generate hypothesis
        if critical_unhealthy:
            return {
                "hypothesis": f"Critical upstream failure: {critical_unhealthy[0]['name']}",
                "confidence": 0.90,
                "evidence": [
                    f"Critical service {critical_unhealthy[0]['name']} is unhealthy",
                    f"Total unhealthy upstream: {len(unhealthy_upstream)}",
                    f"Affected services: {', '.join(services_to_analyze)}",
                ],
                "recommended_action": f"Fix {critical_unhealthy[0]['name']} first, then restart dependent services",
                "affected_upstream": unhealthy_upstream,
            }

        if unhealthy_upstream:
            return {
                "hypothesis": f"Upstream dependency failure: {unhealthy_upstream[0]['name']}",
                "confidence": 0.80,
                "evidence": [
                    f"Unhealthy dependency: {unhealthy_upstream[0]['name']}",
                    f"Total unhealthy: {len(unhealthy_upstream)}",
                ],
                "recommended_action": f"Check and fix {unhealthy_upstream[0]['name']}",
                "affected_upstream": unhealthy_upstream,
            }

        if shared:
            problematic_shared = [s for s in shared if any(health_map.get(svc) != "healthy" for svc in s["services"])]
            if problematic_shared:
                return {
                    "hypothesis": f"Shared resource issue: {problematic_shared[0]['resource']}",
                    "confidence": 0.75,
                    "evidence": [
                        f"Shared resource: {problematic_shared[0]['resource']}",
                        f"Services affected: {', '.join(problematic_shared[0]['services'])}",
                    ],
                    "recommended_action": f"Check resource {problematic_shared[0]['resource']} state",
                    "shared_resources": problematic_shared,
                }

        # Multiple services failing without clear shared cause
        if len(services_to_analyze) > 1:
            return {
                "hypothesis": "Potential network or infrastructure issue",
                "confidence": 0.60,
                "evidence": [
                    f"Multiple services failing: {', '.join(services_to_analyze)}",
                    "No clear shared resource or dependency identified",
                ],
                "recommended_action": "Check network connectivity, DNS, and infrastructure health",
            }

        return {
            "hypothesis": "No clear graph-based root cause",
            "confidence": 0.40,
            "evidence": [
                f"Checked {len(upstream)} upstream dependencies",
                f"Checked {len(shared)} shared resources",
                "All upstream services appear healthy",
            ],
            "recommended_action": "Manual investigation required - check service logs",
        }

    except Exception as e:
        logger.error(f"Root cause analysis failed: {e}", exc_info=True)
        return {
            "hypothesis": "Error during analysis",
            "confidence": 0.0,
            "evidence": [str(e)],
            "recommended_action": "Retry or investigate manually",
        }
