"""Corvus MCP Server — exposes Corvus operations as MCP tools for AI agents.

Run standalone:
    python -m src.mcp_server

Or use with Claude Code MCP config:
    {
        "mcpServers": {
            "corvus": {
                "command": "python",
                "args": ["-m", "src.mcp_server"],
                "env": {"CORVUS_URL": "http://localhost:8000"}
            }
        }
    }
"""

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

CORVUS_URL = os.getenv("CORVUS_URL", "http://localhost:8000")

mcp = FastMCP(
    "corvus",
    instructions=(
        "Corvus operational governance tools. Use these to coordinate with other "
        "agents, check for conflicts before acting, emit events, and manage "
        "incidents/changes/services."
    ),
)


def _client() -> httpx.Client:
    return httpx.Client(base_url=CORVUS_URL, timeout=30)


@mcp.tool()
def ops_check_target(target: str) -> str:
    """Check target status before taking action. Returns GO/CAUTION/STOP recommendation.

    MUST be called before any MODIFY+ action on a target (restart, deploy, config change).
    - GO: Safe to proceed
    - CAUTION: Another agent is working nearby — review before acting
    - STOP: Active critical incident or conflicting change — do not act
    """
    with _client() as client:
        resp = client.get(f"/ops/events/targets/{target}/status")
        resp.raise_for_status()
        data = resp.json()
        return json.dumps(data, indent=2)


@mcp.tool()
def ops_watch_events(
    since: str | None = None,
    min_severity: str | None = None,
    target: str | None = None,
    limit: int = 20,
) -> str:
    """Watch operational events from other agents.

    Use this to stay aware of what's happening across the fleet.
    Call periodically during long sessions or before major actions.

    Args:
        since: ISO8601 timestamp — only events after this time
        min_severity: Minimum severity filter (info, warning, critical)
        target: Filter to specific target/service
        limit: Max events to return (default 20)
    """
    params: dict = {"limit": limit}
    if since:
        params["since"] = since
    if min_severity:
        params["severity"] = min_severity
    if target:
        params["target"] = target

    with _client() as client:
        resp = client.get("/ops/events", params=params)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_emit_event(
    source: str,
    event_type: str,
    target: str,
    severity: str = "info",
    data: dict | None = None,
    related_incident_id: str | None = None,
    related_change_id: str | None = None,
) -> str:
    """Emit an operational event for an action you've taken.

    MUST be called after any state-changing action (restart, deploy, config change, investigation).

    Common event types:
    - change.started / change.completed / change.failed
    - incident.opened / incident.investigating / incident.resolved / incident.escalated
    - remediation.restart / remediation.config_fix / remediation.credential_rotation
    - sweep.completed / sweep.anomaly
    - session.started / session.ended

    Args:
        source: Your agent identity (e.g., "claude-code", "nemoclaw")
        event_type: Event type from the taxonomy above
        target: The service/container affected
        severity: info, warning, or critical
        data: Additional event data (include "summary" key for human-readable description)
        related_incident_id: Link to related incident (e.g., "INC-042")
        related_change_id: Link to related change window (e.g., "CHG-001")
    """
    body: dict = {
        "source": source,
        "type": event_type,
        "target": target,
        "severity": severity,
        "data": data or {},
    }
    if related_incident_id:
        body["related_incident_id"] = related_incident_id
    if related_change_id:
        body["related_change_id"] = related_change_id

    with _client() as client:
        resp = client.post("/ops/events", json=body)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_create_incident(
    target: str,
    title: str,
    description: str | None = None,
    severity: str = "medium",
    detected_by: str = "claude-code",
) -> str:
    """Create an incident record when you detect or investigate an issue.

    Use this instead of just reporting in markdown — creates a trackable record
    that other agents can see and correlate.

    Args:
        target: The affected service/container
        title: Short incident title
        description: Detailed description of what happened
        severity: low, medium, high, or critical
        detected_by: Your agent identity (e.g., "claude-code:responder")
    """
    with _client() as client:
        resp = client.post(
            "/ops/incidents",
            json={
                "target": target,
                "title": title,
                "description": description,
                "severity": severity,
                "detected_by": detected_by,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_create_change(
    targets: list[str],
    description: str,
    created_by: str = "claude-code",
    rollback_plan: str | None = None,
    project: str | None = None,
) -> str:
    """Declare a change window before making infrastructure changes.

    This tells other agents you're working on these targets. They'll see
    CAUTION or STOP when they check target status.

    Change windows auto-expire after 4 hours.

    Args:
        targets: List of services/containers being changed
        description: What you're doing
        created_by: Your agent identity
        rollback_plan: How to undo this change if it fails
        project: Related project or issue reference
    """
    body: dict = {
        "targets": targets,
        "description": description,
        "created_by": created_by,
    }
    if rollback_plan:
        body["rollback_plan"] = rollback_plan
    if project:
        body["project"] = project

    with _client() as client:
        resp = client.post("/ops/changes", json=body)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_close_change(change_id: str, outcome: str = "success") -> str:
    """Close a change window after completing your work.

    Args:
        change_id: The change ID (e.g., "CHG-A1B2C3D4")
        outcome: Result — "success", "partial", or "failed"
    """
    with _client() as client:
        resp = client.patch(
            f"/ops/changes/{change_id}",
            json={
                "status": "completed",
                "outcome": outcome,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_get_context() -> str:
    """Get session start briefing — last 24h events sorted by severity.

    Call this at the start of a session to understand what's been happening.
    Returns recent events, prioritized by severity.
    """
    with _client() as client:
        resp = client.get("/ops/events/context")
        resp.raise_for_status()
        events = resp.json()
        if not events:
            return "No events in the last 24 hours. All quiet."
        return json.dumps(events, indent=2)


@mcp.tool()
def ops_list_services(
    service_type: str | None = None,
    critical: bool | None = None,
    host: str | None = None,
) -> str:
    """Query the CMDB for registered services.

    Args:
        service_type: Filter by type (inference, database, proxy, mcp_bridge, etc.)
        critical: Filter to critical services only
        host: Filter by host
    """
    params: dict = {}
    if service_type:
        params["service_type"] = service_type
    if critical is not None:
        params["critical"] = critical
    if host:
        params["host"] = host

    with _client() as client:
        resp = client.get("/ops/cmdb", params=params)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_register_service(
    name: str,
    host: str | None = None,
    service_type: str | None = None,
    critical: bool = False,
    dependencies: list[str] | None = None,
    registered_by: str = "claude-code",
) -> str:
    """Register or update a service in the CMDB.

    If the service already exists, it will be updated with the new values.

    Args:
        name: Service/container name
        host: Host where it runs
        service_type: Classification (inference, database, proxy, mcp_bridge,
                      secrets, iot_gateway, home_automation, media, monitoring,
                      automation, dns, utility)
        critical: Whether this is on the critical path
        dependencies: List of service names this depends on
        registered_by: Your agent identity
    """
    with _client() as client:
        resp = client.post(
            "/ops/cmdb/register",
            json={
                "name": name,
                "host": host,
                "service_type": service_type,
                "critical": critical,
                "dependencies": dependencies or [],
                "registered_by": registered_by,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_run_triage(
    target: str,
    host: str = "",
    service_type: str | None = None,
    investigation_data: dict | None = None,
) -> str:
    """Run FMEA triage on a target using the matching runbook.

    Selects the runbook by service_type (from CMDB if not provided),
    runs investigation steps, and returns a diagnosis with remediation guidance.

    Args:
        target: Service/container to triage
        host: Host where it runs
        service_type: Override service type (looked up from CMDB if omitted)
        investigation_data: Pre-collected investigation data (logs, metrics, etc.)
    """
    body: dict = {"target": target, "host": host}
    if service_type:
        body["service_type"] = service_type
    if investigation_data:
        body["investigation_data"] = investigation_data

    with _client() as client:
        resp = client.post("/ops/runbooks/triage", json=body)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_get_metrics() -> str:
    """Get operational dashboard metrics.

    Returns: event counts, open incidents/problems, gap counts by workstream,
    false positive rate, CMDB stats, SIEM forwarding stats, runbook coverage.
    """
    with _client() as client:
        resp = client.get("/ops/metrics")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_report_gap(
    title: str,
    pattern: str,
    root_cause: str = "",
    recommended_fix: str = "",
    workstream: str = "CI",
    severity: str = "medium",
) -> str:
    """Report a blind spot / gap in operational coverage.

    Use this when you encounter something the system doesn't handle well —
    a failure you can't diagnose, a service type without a runbook, etc.

    Args:
        title: Human-readable gap description
        pattern: Gap pattern (e.g., "gap:coverage:no-runbook:my_service_type")
        root_cause: Why this gap exists
        recommended_fix: What should be done to close the gap
        workstream: "CI" (improve existing) or "NFI" (build new capability)
        severity: low, medium, high, or critical
    """
    with _client() as client:
        resp = client.post(
            "/ops/problems",
            json={
                "title": title,
                "pattern": pattern,
                "root_cause": root_cause,
                "recommended_fix": recommended_fix,
                "workstream": workstream,
                "severity": severity,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


if __name__ == "__main__":
    mcp.run()
