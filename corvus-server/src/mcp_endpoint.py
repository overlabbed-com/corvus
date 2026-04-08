"""Embedded MCP server for Corvus.

Exposes Corvus operations as MCP tools via Streamable HTTP transport,
mounted directly on the FastAPI app. Clients send POST requests to /mcp
with JSON-RPC bodies.

Internal calls use httpx.AsyncClient with ASGITransport — zero network
overhead, full request/response fidelity, and clean separation from router
internals.
"""

import json
import logging
from typing import Any

import httpx
from mcp.server import Server
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Mount

from src.config import MCP_INTERNAL_KEY
from src.sanitizer import sanitize

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP Server instance
# ---------------------------------------------------------------------------
mcp_server = Server("corvus")

# ---------------------------------------------------------------------------
# Internal HTTP client (set up when create_mcp_routes is called)
# ---------------------------------------------------------------------------
_internal_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the internal ASGI HTTP client."""
    if _internal_client is None:
        raise RuntimeError("MCP internal client not initialised — call create_mcp_routes first")
    return _internal_client


def _auth_headers() -> dict[str, str]:
    """Auth headers for internal API calls."""
    return {"Authorization": f"Bearer {MCP_INTERNAL_KEY}"}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS: list[Tool] = [
    # -- Graph queries --
    Tool(
        name="corvus_blast_radius",
        description=(
            "What services break if this one goes down. Returns affected services "
            "with host, stack, and dependency depth."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name to analyse"},
            },
            "required": ["service"],
        },
    ),
    Tool(
        name="corvus_dependency_chain",
        description="Full upstream dependency path for a service.",
        inputSchema={
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name"},
            },
            "required": ["service"],
        },
    ),
    Tool(
        name="corvus_expiring_cis",
        description=("CIs (certs, accounts, licenses) expiring within N days."),
        inputSchema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Look-ahead window in days (default 30)",
                    "default": 30,
                },
            },
        },
    ),
    Tool(
        name="corvus_correlated_gpu",
        description="Services sharing a specific GPU on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Hostname"},
                "gpu_index": {"type": "integer", "description": "GPU device index"},
            },
            "required": ["host", "gpu_index"],
        },
    ),
    Tool(
        name="corvus_graph_stats",
        description="Node and edge counts in the operational graph.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # -- Triage --
    Tool(
        name="corvus_triage",
        description=(
            "Submit investigation evidence for runbook-based diagnosis. Returns "
            "root cause, confidence, and remediation advice."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Affected target"},
                "host": {"type": "string", "description": "Host where target runs", "default": ""},
                "service_type": {"type": "string", "description": "Service type hint"},
                "investigation_data": {
                    "type": "object",
                    "description": "Evidence collected during investigation",
                },
            },
            "required": ["target"],
        },
    ),
    # -- SOP: conflict check --
    Tool(
        name="corvus_check_target",
        description=(
            "Pre-action conflict check. Returns GO / CAUTION / STOP recommendation. "
            "MUST be called before any MODIFY+ action on a target."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target name to check"},
            },
            "required": ["target"],
        },
    ),
    # -- SOP: incidents --
    Tool(
        name="corvus_create_incident",
        description="Create an operational incident record.",
        inputSchema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Affected target"},
                "title": {"type": "string", "description": "Short incident title"},
                "description": {"type": "string", "description": "Detailed description"},
                "severity": {
                    "type": "string",
                    "description": "warning or critical",
                    "enum": ["warning", "critical"],
                    "default": "warning",
                },
                "detected_by": {
                    "type": "string",
                    "description": "Who detected it",
                    "default": "mcp-agent",
                },
            },
            "required": ["target", "title"],
        },
    ),
    Tool(
        name="corvus_list_incidents",
        description="List incidents with optional filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status (open, investigating, resolved)"},
                "target": {"type": "string", "description": "Filter by target name"},
                "severity": {"type": "string", "description": "Filter by severity (warning, critical)"},
            },
        },
    ),
    # -- SOP: events --
    Tool(
        name="corvus_emit_event",
        description="Emit an operational event to the event stream.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Event source (e.g. my-agent, ops-bot)"},
                "type": {"type": "string", "description": "Event type (e.g. change.started, remediation.restart)"},
                "target": {"type": "string", "description": "Affected target", "default": ""},
                "severity": {
                    "type": "string",
                    "description": "info, warning, or critical",
                    "enum": ["info", "warning", "critical"],
                    "default": "info",
                },
                "data": {"type": "object", "description": "Event-specific data", "default": {}},
            },
            "required": ["source", "type"],
        },
    ),
    Tool(
        name="corvus_watch_events",
        description="List recent operational events with optional filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "ISO8601 timestamp — only events after this"},
                "severity": {"type": "string", "description": "Minimum severity filter"},
                "target": {"type": "string", "description": "Filter by target"},
                "limit": {"type": "integer", "description": "Max events to return", "default": 50},
            },
        },
    ),
    Tool(
        name="corvus_get_context",
        description=(
            "Session briefing — last 24h of operational events sorted by severity. "
            "Call at session start to understand current state."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    # -- SOP: changes --
    Tool(
        name="corvus_create_change",
        description=(
            "Declare a change window before modifying infrastructure. Suppresses alerts for specified targets."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of target names affected by the change",
                },
                "description": {"type": "string", "description": "What is being changed and why"},
                "operator": {"type": "string", "description": "Who is making the change", "default": "mcp-agent"},
                "rollback_plan": {"type": "string", "description": "How to undo the change", "default": ""},
                "project": {"type": "string", "description": "Project reference", "default": ""},
            },
            "required": ["targets", "description"],
        },
    ),
    # -- CMDB --
    Tool(
        name="corvus_get_service",
        description=("Get service metadata from CMDB — type, dependencies, baselines, alert policy."),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Service name"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="corvus_list_services",
        description="List all services in CMDB with optional filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "service_type": {"type": "string", "description": "Filter by service type"},
                "host": {"type": "string", "description": "Filter by host"},
                "critical": {"type": "boolean", "description": "Filter by criticality"},
            },
        },
    ),
    # -- Config Drift --
    Tool(
        name="corvus_config_drift",
        description=(
            "Find services where running config diverges from declared compose state. "
            "Detects stale containers that need force-recreate — e.g., healthcheck added "
            "to compose but missing from running container."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Optional service name for detailed single-service drift report",
                },
            },
        },
    ),
    # -- Discovery --
    Tool(
        name="corvus_discovery_bootstrap",
        description="Trigger full service discovery from compose files.",
        inputSchema={
            "type": "object",
            "properties": {
                "compose_dir": {"type": "string", "description": "Path to compose directory"},
            },
            "required": ["compose_dir"],
        },
    ),
    Tool(
        name="corvus_discovery_coverage",
        description="Discovery coverage report — services with no deps, stale edges.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # -- Discovery Layer 2 --
    Tool(
        name="corvus_observe_connections",
        description=(
            "Ingest observed TCP connections (Layer 2: Observed). "
            "Accepts pre-parsed connection tuples, conntrack output, or Tetragon events. "
            "Resolves IPs to container names and creates OBSERVED_CONNECTION graph edges."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Input format: tuples, conntrack, or tetragon",
                    "enum": ["tuples", "conntrack", "tetragon"],
                    "default": "tuples",
                },
                "host": {"type": "string", "description": "Source host name"},
                "connections": {
                    "type": "array",
                    "description": "Connection tuples (for format=tuples)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "src_ip": {"type": "string"},
                            "dst_ip": {"type": "string"},
                            "src_port": {"type": "integer"},
                            "dst_port": {"type": "integer"},
                        },
                        "required": ["src_ip", "dst_ip"],
                    },
                    "default": [],
                },
                "raw_text": {
                    "type": "string",
                    "description": "Raw conntrack -L output (for format=conntrack)",
                },
            },
        },
    ),
    Tool(
        name="corvus_list_connections",
        description="List all observed service-to-service connections from network traffic.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="corvus_collect_connections",
        description=(
            "Trigger an on-demand Layer 2 collection sweep. Corvus queries Docker hosts "
            "directly via Docker API: network inspect for IP mapping, /proc/net/tcp via "
            "exec for active connections. Resolves to service-to-service edges."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    # -- Discovery Layers 4-6 --
    Tool(
        name="corvus_report_dependency",
        description=(
            "Report a discovered dependency or CI to the graph (Layer 4: Reported). "
            "Agents and services self-register their CIs and dependencies."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "reporter": {"type": "string", "description": "Who is reporting (e.g. my-agent, ops-bot)"},
                "services": {
                    "type": "array",
                    "description": "Services to register",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "host": {"type": "string"},
                            "service_type": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                    "default": [],
                },
                "edges": {
                    "type": "array",
                    "description": "Dependency edges to register",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                            "type": {"type": "string", "default": "DEPENDS_ON"},
                            "confidence": {"type": "number", "default": 0.8},
                        },
                        "required": ["source", "target"],
                    },
                    "default": [],
                },
                "cis": {
                    "type": "array",
                    "description": "Configuration items to register",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "name": {"type": "string"},
                            "service": {"type": "string"},
                            "properties": {"type": "object"},
                        },
                        "required": ["type", "name", "service"],
                    },
                    "default": [],
                },
            },
            "required": ["reporter"],
        },
    ),
    Tool(
        name="corvus_run_inference",
        description=(
            "Trigger temporal correlation analysis (Layer 5: Inferred). "
            "Mines incident co-occurrence and change cascades to find implicit dependencies."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="corvus_list_suggestions",
        description="View inferred dependency edges awaiting human validation.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="corvus_validate_suggestion",
        description=(
            "Accept or reject an inferred dependency. If valid, upgrades to "
            "DEPENDS_ON with high confidence. If rejected, deletes the edge."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source service name"},
                "target": {"type": "string", "description": "Target service name"},
                "valid": {"type": "boolean", "description": "True to accept, false to reject"},
                "notes": {"type": "string", "description": "Validation notes", "default": ""},
            },
            "required": ["source", "target", "valid"],
        },
    ),
    Tool(
        name="corvus_report_knowledge",
        description=(
            "Capture a dependency discovery as tribal knowledge (Layer 6: Elicited). "
            "Typically used during incident resolution when dependencies are discovered."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Knowledge source (e.g. my-agent:session)"},
                "from_service": {"type": "string", "description": "Service that depends"},
                "to_service": {"type": "string", "description": "Service depended upon"},
                "relationship": {
                    "type": "string",
                    "description": "Relationship type (default DEPENDS_ON)",
                    "default": "DEPENDS_ON",
                },
                "notes": {"type": "string", "description": "Context about the dependency", "default": ""},
                "confidence": {"type": "number", "description": "Confidence level (0-1)", "default": 0.95},
            },
            "required": ["source", "from_service", "to_service"],
        },
    ),
    # -- Step execution (async triage) --
    Tool(
        name="corvus_pending_steps",
        description=(
            "List pending runbook steps waiting for agent execution. "
            "Returns step_id, type, and params for each step the agent needs to run."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "triage_id": {
                    "type": "string",
                    "description": "Filter by triage ID (optional)",
                },
            },
        },
    ),
    Tool(
        name="corvus_submit_step",
        description=(
            "Submit the result of executing a runbook step. After executing "
            "a step (e.g. checking logs, running nvidia-smi), report the output here."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "step_id": {"type": "string", "description": "Step ID from pending steps"},
                "output": {
                    "type": "object",
                    "description": "Step execution output (any JSON)",
                },
                "error": {"type": "string", "description": "Error message if step failed"},
                "success": {
                    "type": "boolean",
                    "description": "Whether the step succeeded",
                    "default": True,
                },
            },
            "required": ["step_id"],
        },
    ),
    Tool(
        name="corvus_async_triage",
        description=(
            "Start an async triage — returns pending steps for agent execution. "
            "Use this instead of corvus_triage when you can execute investigation "
            "steps yourself (SSH, Docker, etc). After executing steps, call "
            "corvus_continue_triage to get the diagnosis."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Affected target"},
                "host": {"type": "string", "description": "Host where target runs", "default": ""},
                "service_type": {"type": "string", "description": "Service type hint"},
            },
            "required": ["target"],
        },
    ),
    Tool(
        name="corvus_continue_triage",
        description=(
            "Continue triage after submitting all step results. Returns diagnosis, root cause, and remediation advice."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "triage_id": {"type": "string", "description": "Triage ID from async_triage"},
            },
            "required": ["triage_id"],
        },
    ),
    # -- Gaps / Blind Spots --
    Tool(
        name="corvus_gap_summary",
        description=(
            "Summary of all open operational gaps — blind spots in coverage, accuracy, monitoring, and autonomy."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="corvus_gap_sweep",
        description="Trigger a manual gap detection sweep. Checks for untyped services, unseen services, "
        "stale findings, stuck escalations, and generic fallback triages.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # -- Cleanup --
    Tool(
        name="corvus_cleanup",
        description="Trigger event/audit/triage log cleanup. Prunes records older than retention period.",
        inputSchema={
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview what would be deleted without actually deleting",
                    "default": False,
                },
            },
        },
    ),
    # -- Knowledge --
    Tool(
        name="corvus_knowledge_search",
        description=(
            "Search operational knowledge for past resolutions, triage results, and problem patterns. "
            "Use BEFORE escalating — the answer may already exist from a past incident."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search query (e.g. 'inference OOM restart', 'proxy TLS error')",
                },
                "source_type": {
                    "type": "string",
                    "description": "Filter: incident, problem, triage, or manual",
                },
                "service_type": {"type": "string", "description": "Filter by service type (e.g. inference, proxy)"},
                "target": {"type": "string", "description": "Filter by target service name"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["q"],
        },
    ),
    Tool(
        name="corvus_knowledge_add",
        description=(
            "Add operational knowledge manually — a learning, pattern, or resolution "
            "that should be findable in future searches."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short descriptive title"},
                "content": {"type": "string", "description": "Full knowledge content — diagnosis, fix, context"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization",
                },
                "service_type": {"type": "string", "description": "Service type this applies to"},
                "target": {"type": "string", "description": "Specific target service"},
            },
            "required": ["title", "content"],
        },
    ),
    # -- Compliance --
    Tool(
        name="corvus_compliance_audit",
        description="Run a compliance audit — check event emission coverage for changes and incidents. "
        "Use at session end to verify all MODIFY+ actions emitted corresponding events.",
        inputSchema={
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "ISO8601 timestamp — only audit items after this"},
                "source": {"type": "string", "description": "Agent name filter (e.g. my-agent, ops-bot)"},
            },
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool routing — maps MCP tool names to internal API calls
# ---------------------------------------------------------------------------
async def _call_api(method: str, path: str, params: dict | None = None, body: Any = None) -> dict:
    """Make an internal API call and return the JSON response."""
    client = _get_client()
    kwargs: dict[str, Any] = {"headers": _auth_headers()}
    if params:
        kwargs["params"] = params
    if body is not None:
        kwargs["json"] = body

    if method == "GET":
        resp = await client.get(path, **kwargs)
    elif method == "POST":
        resp = await client.post(path, **kwargs)
    else:
        resp = await client.request(method, path, **kwargs)

    if resp.status_code >= 400:
        return {"error": resp.text, "status": resp.status_code}
    return resp.json()


async def _dispatch_tool(name: str, args: dict[str, Any]) -> str:
    """Route a tool call to the appropriate internal API endpoint."""

    # -- Graph queries --
    if name == "corvus_blast_radius":
        result = await _call_api("GET", f"/ops/graph/blast-radius/{args['service']}")

    elif name == "corvus_dependency_chain":
        result = await _call_api("GET", f"/ops/graph/dependency-chain/{args['service']}")

    elif name == "corvus_expiring_cis":
        days = args.get("days", 30)
        result = await _call_api("GET", "/ops/graph/expiring", params={"days": days})

    elif name == "corvus_correlated_gpu":
        result = await _call_api(
            "GET",
            f"/ops/graph/correlated/{args['host']}/{args['gpu_index']}",
        )

    elif name == "corvus_graph_stats":
        result = await _call_api("GET", "/ops/graph/stats")

    # -- Triage --
    elif name == "corvus_triage":
        body = {
            "target": args["target"],
            "host": args.get("host", ""),
            "service_type": args.get("service_type"),
            "investigation_data": args.get("investigation_data"),
        }
        result = await _call_api("POST", "/ops/runbooks/triage", body=body)

    # -- SOP: conflict check --
    elif name == "corvus_check_target":
        result = await _call_api("GET", f"/ops/events/targets/{args['target']}/status")

    # -- SOP: incidents --
    elif name == "corvus_create_incident":
        body = {
            "target": args["target"],
            "title": args["title"],
            "description": args.get("description", ""),
            "severity": args.get("severity", "warning"),
            "detected_by": args.get("detected_by", "mcp-agent"),
        }
        result = await _call_api("POST", "/ops/incidents", body=body)

    elif name == "corvus_list_incidents":
        params = {}
        for key in ("status", "target", "severity"):
            if args.get(key):
                params[key] = args[key]
        result = await _call_api("GET", "/ops/incidents", params=params)

    # -- SOP: events --
    elif name == "corvus_emit_event":
        body = {
            "source": args["source"],
            "type": args["type"],
            "target": args.get("target", ""),
            "severity": args.get("severity", "info"),
            "data": args.get("data", {}),
        }
        result = await _call_api("POST", "/ops/events", body=body)

    elif name == "corvus_watch_events":
        params = {}
        if args.get("since"):
            params["since"] = args["since"]
        if args.get("severity"):
            params["severity"] = args["severity"]
        if args.get("target"):
            params["target"] = args["target"]
        params["limit"] = args.get("limit", 50)
        result = await _call_api("GET", "/ops/events", params=params)

    elif name == "corvus_get_context":
        result = await _call_api("GET", "/ops/events/context")

    # -- SOP: changes --
    elif name == "corvus_create_change":
        body = {
            "targets": args["targets"],
            "description": args["description"],
            "created_by": args.get("operator", "mcp-agent"),
            "rollback_plan": args.get("rollback_plan", ""),
            "project": args.get("project", ""),
        }
        result = await _call_api("POST", "/ops/changes", body=body)

    # -- CMDB --
    elif name == "corvus_get_service":
        result = await _call_api("GET", f"/ops/cmdb/{args['name']}")

    elif name == "corvus_list_services":
        params = {}
        for key in ("service_type", "host"):
            if args.get(key):
                params[key] = args[key]
        if "critical" in args and args["critical"] is not None:
            params["critical"] = str(args["critical"]).lower()
        result = await _call_api("GET", "/ops/cmdb", params=params)

    # -- Config Drift --
    elif name == "corvus_config_drift":
        service = args.get("service")
        if service:
            result = await _call_api("GET", f"/ops/graph/drift/{service}")
        else:
            result = await _call_api("GET", "/ops/graph/drift")

    # -- Discovery --
    elif name == "corvus_discovery_bootstrap":
        body = {"compose_dir": args["compose_dir"]}
        result = await _call_api("POST", "/ops/discovery/bootstrap", body=body)

    elif name == "corvus_discovery_coverage":
        result = await _call_api("GET", "/ops/discovery/coverage")

    # -- Discovery Layer 2 --
    elif name == "corvus_observe_connections":
        body = {
            "format": args.get("format", "tuples"),
            "host": args.get("host", ""),
            "connections": args.get("connections", []),
            "raw_text": args.get("raw_text", ""),
        }
        result = await _call_api("POST", "/ops/discovery/connections", body=body)

    elif name == "corvus_list_connections":
        result = await _call_api("GET", "/ops/discovery/connections")

    elif name == "corvus_collect_connections":
        result = await _call_api("POST", "/ops/discovery/collect")

    # -- Discovery Layers 4-6 --
    elif name == "corvus_report_dependency":
        body = {
            "reporter": args["reporter"],
            "services": args.get("services", []),
            "edges": args.get("edges", []),
            "cis": args.get("cis", []),
        }
        result = await _call_api("POST", "/ops/discovery/report", body=body)

    elif name == "corvus_run_inference":
        result = await _call_api("POST", "/ops/discovery/infer")

    elif name == "corvus_list_suggestions":
        result = await _call_api("GET", "/ops/discovery/suggestions")

    elif name == "corvus_validate_suggestion":
        body = {
            "valid": args["valid"],
            "notes": args.get("notes", ""),
        }
        result = await _call_api(
            "POST",
            f"/ops/discovery/suggestions/{args['source']}/{args['target']}/validate",
            body=body,
        )

    elif name == "corvus_report_knowledge":
        body = {
            "source": args["source"],
            "from_service": args["from_service"],
            "to_service": args["to_service"],
            "relationship": args.get("relationship", "DEPENDS_ON"),
            "notes": args.get("notes", ""),
            "confidence": args.get("confidence", 0.95),
        }
        result = await _call_api("POST", "/ops/discovery/knowledge", body=body)

    # -- Step execution (async triage) --
    elif name == "corvus_pending_steps":
        params = {}
        if args.get("triage_id"):
            params["triage_id"] = args["triage_id"]
        result = await _call_api("GET", "/ops/runbooks/steps/pending", params=params)

    elif name == "corvus_submit_step":
        body = {
            "output": args.get("output"),
            "error": args.get("error"),
            "success": args.get("success", True),
        }
        result = await _call_api("POST", f"/ops/runbooks/steps/{args['step_id']}/result", body=body)

    elif name == "corvus_async_triage":
        body = {
            "target": args["target"],
            "host": args.get("host", ""),
            "service_type": args.get("service_type"),
        }
        result = await _call_api("POST", "/ops/runbooks/steps/triage/async", body=body)

    elif name == "corvus_continue_triage":
        result = await _call_api("POST", f"/ops/runbooks/steps/triage/{args['triage_id']}/continue")

    # -- Knowledge --
    elif name == "corvus_knowledge_search":
        params = {"q": args["q"]}
        for key in ("source_type", "service_type", "target"):
            if args.get(key):
                params[key] = args[key]
        if args.get("limit"):
            params["limit"] = args["limit"]
        result = await _call_api("GET", "/ops/knowledge/search", params=params)

    elif name == "corvus_knowledge_add":
        body = {
            "title": args["title"],
            "content": args["content"],
            "source_type": "manual",
            "tags": args.get("tags", []),
            "service_type": args.get("service_type"),
            "target": args.get("target"),
        }
        result = await _call_api("POST", "/ops/knowledge", body=body)

    # -- Gaps / Blind Spots --
    elif name == "corvus_gap_summary":
        result = await _call_api("GET", "/ops/gaps")

    elif name == "corvus_gap_sweep":
        result = await _call_api("POST", "/ops/gaps/sweep")

    # -- Cleanup --
    elif name == "corvus_cleanup":
        params = {}
        if args.get("dry_run"):
            params["dry_run"] = "true"
        result = await _call_api("POST", "/ops/cleanup", params=params)

    # -- Compliance --
    elif name == "corvus_compliance_audit":
        params = {}
        if args.get("since"):
            params["since"] = args["since"]
        if args.get("source"):
            params["source"] = args["source"]
        result = await _call_api("GET", "/ops/metrics/compliance", params=params)

    else:
        result = {"error": f"Unknown tool: {name}"}

    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Register handlers on the MCP server
# ---------------------------------------------------------------------------
@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOL_DEFINITIONS


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    logger.info("MCP tool call: %s", name)
    try:
        result_text = await _dispatch_tool(name, arguments)
    except Exception as exc:
        logger.exception("MCP tool %s failed", name)
        result_text = json.dumps({"error": str(exc)})
    # Sanitize all tool responses before returning to agents
    result_text = sanitize(result_text)
    return [TextContent(type="text", text=result_text)]


# ---------------------------------------------------------------------------
# Streamable HTTP transport + Starlette routes
# ---------------------------------------------------------------------------
def create_mcp_routes(fastapi_app: Any) -> Starlette:
    """Build a Starlette sub-application serving the MCP Streamable HTTP endpoint.

    The returned app is mounted on the FastAPI app at ``/mcp``.
    Clients send POST requests to ``/mcp`` with JSON-RPC bodies.

    Args:
        fastapi_app: The FastAPI ``app`` instance — used to create an internal
            ASGI HTTP client so MCP tool handlers can call Corvus endpoints
            without a network round-trip.
    """
    global _internal_client

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    # Internal client — ASGI transport means zero network overhead
    _internal_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url="http://internal",
    )

    # Stateless session manager — each request creates a fresh session.
    # JSON response mode for simpler HTTP semantics (no SSE streaming).
    http_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        stateless=True,
        json_response=True,
    )

    async def handle_mcp(scope, receive, send):
        """Streamable HTTP endpoint — handles POST/GET/DELETE at /mcp."""
        await http_manager.handle_request(scope, receive, send)

    mcp_app = Starlette(
        routes=[
            Mount("/", app=handle_mcp),
        ],
    )

    logger.info("MCP Streamable HTTP endpoint created (%d tools registered)", len(TOOL_DEFINITIONS))
    return mcp_app
