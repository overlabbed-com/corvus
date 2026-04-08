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
        source: Your agent identity (e.g., "my-agent", "ops-bot")
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
    detected_by: str = "mcp-agent",
) -> str:
    """Create an incident record when you detect or investigate an issue.

    Use this instead of just reporting in markdown — creates a trackable record
    that other agents can see and correlate.

    Args:
        target: The affected service/container
        title: Short incident title
        description: Detailed description of what happened
        severity: low, medium, high, or critical
        detected_by: Your agent identity (e.g., "my-agent:responder")
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
    created_by: str = "mcp-agent",
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
    registered_by: str = "mcp-agent",
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


# ---- Plan execution tools ----


@mcp.tool()
def ops_create_plan(
    title: str,
    description: str,
    steps: list[dict],
    created_by: str = "mcp-agent",
) -> str:
    """Create a structured execution plan with DAG-ordered steps.

    Plans enable CC to design multi-step work orders that NemoClaw executes
    asynchronously. Steps can run in parallel (fleet fan-out) or sequentially
    (DAG dependencies).

    Args:
        title: Human-readable plan title
        description: What this plan accomplishes
        steps: List of step definitions. Each step dict should contain:
            - name: Step name (used for depends_on references)
            - sequence: Execution order within dependency group
            - action_type: Trust ledger key (e.g., "change.deploy", "health.check")
            - targets: List of target services/containers
            - depends_on: List of step names this depends on (optional, default [])
            - failure_policy: "halt" (default), "skip", or "retry"
            - max_retries: Max retry attempts (default 0, only used with retry policy)
            - rollback: Rollback definition dict (required for mutations)
            - timeout: Step timeout in seconds (default 300)
        created_by: Your agent identity
    """
    with _client() as client:
        resp = client.post(
            "/ops/plans",
            json={
                "title": title,
                "description": description,
                "steps": steps,
                "created_by": created_by,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_approve_plan(
    plan_id: str,
    approved_by: str = "mcp-agent",
    force: bool = False,
) -> str:
    """Approve a plan for execution using trust ledger gating.

    Checks each step's action_type against the trust ledger:
    - All AUTO/SUPERVISED: auto-approves
    - Any ESCALATE: returns needs_approval with escalated steps list
    - force=True: human override, approves regardless of trust tiers

    Args:
        plan_id: Plan ID (e.g., "PLN-A1B2C3D4")
        approved_by: Identity of approver
        force: Human override — approve despite ESCALATE steps
    """
    with _client() as client:
        resp = client.post(
            f"/ops/plans/{plan_id}/approve",
            json={
                "approved_by": approved_by,
                "force": force,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_execute_plan(plan_id: str) -> str:
    """Start plan execution: creates change window, marks root steps ready.

    Only approved plans can be executed. Creates a change window covering
    all plan targets and emits plan.started event.

    Args:
        plan_id: Plan ID to execute
    """
    with _client() as client:
        resp = client.post(f"/ops/plans/{plan_id}/execute")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_plan_status(plan_id: str) -> str:
    """Get plan execution summary with step counts and progress.

    Returns total steps, counts by status (pending/ready/executing/completed/
    failed/skipped), progress percentage, and change window ID.

    Args:
        plan_id: Plan ID to check
    """
    with _client() as client:
        resp = client.get(f"/ops/plans/{plan_id}/status")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_pull_ready_steps(plan_id: str) -> str:
    """Pull steps ready for execution. Claims them by marking as executing.

    Returns steps whose dependencies are all satisfied. Each returned step
    is atomically claimed (status: executing, started_at set). Call this
    to get work, execute it, then report results.

    Args:
        plan_id: Plan ID to pull steps from
    """
    with _client() as client:
        resp = client.post(f"/ops/plans/{plan_id}/steps/ready")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_report_step_result(
    plan_id: str,
    step_id: str,
    success: bool,
    output: dict | None = None,
    error: str | None = None,
) -> str:
    """Report step execution result and advance the DAG.

    On success: marks step completed, evaluates DAG for next ready steps.
    On failure: applies step's failure_policy (halt/skip/retry).

    Returns step status, plan status, retry count, and next ready steps.

    Args:
        plan_id: Plan ID
        step_id: Step ID that was executed
        success: Whether execution succeeded
        output: Execution output data (optional)
        error: Error message if failed (optional)
    """
    body: dict = {"success": success}
    if output is not None:
        body["output"] = output
    if error is not None:
        body["error"] = error

    with _client() as client:
        resp = client.post(
            f"/ops/plans/{plan_id}/steps/{step_id}/result",
            json=body,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_cancel_plan(plan_id: str) -> str:
    """Cancel a plan. Only draft, approved, or blocked plans can be cancelled.

    Args:
        plan_id: Plan ID to cancel
    """
    with _client() as client:
        resp = client.post(f"/ops/plans/{plan_id}/cancel")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_rollback_plan(plan_id: str) -> str:
    """Trigger plan rollback: creates reverse-order rollback steps.

    Only completed or blocked plans can be rolled back. Creates rollback
    steps for each completed step that has a rollback definition, chained
    in reverse sequence order.

    Args:
        plan_id: Plan ID to roll back
    """
    with _client() as client:
        resp = client.post(f"/ops/plans/{plan_id}/rollback")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


# ---- Lean metrics tools ----


@mcp.tool()
def ops_lean_metrics() -> str:
    """Get current lean metrics snapshot — cycle times, throughput, efficiency.
    Call at session start to understand operational health trends."""
    with _client() as client:
        resp = client.get("/ops/lean-metrics")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_bottlenecks(top_n: int = 5) -> str:
    """Identify the slowest processes ranked by cycle time deviation from baseline.
    Shows where to focus improvement efforts."""
    with _client() as client:
        resp = client.get("/ops/lean-metrics/bottlenecks", params={"top_n": top_n})
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_throughput(entity: str = "incidents", hours: int = 168) -> str:
    """Get demand vs capacity analysis — event counts bucketed by hour/day.
    Entity: incidents, plans, triages, changes, steps."""
    with _client() as client:
        resp = client.get(
            "/ops/lean-metrics/throughput",
            params={"entity": entity, "hours": hours},
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ops_convergence() -> str:
    """Check auto-tuning convergence status per parameter.
    Shows whether parameters are still learning or have settled."""
    with _client() as client:
        resp = client.get("/ops/lean-metrics/convergence")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


if __name__ == "__main__":
    mcp.run()
