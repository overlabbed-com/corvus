"""Tests for the embedded MCP endpoint.

Verifies tool registration, tool dispatch via internal ASGI calls,
and the SSE mount point.
"""

import pytest

from src.mcp_endpoint import (
    TOOL_DEFINITIONS,
    _dispatch_tool,
    call_tool,
)

# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------
EXPECTED_TOOLS = {
    "corvus_blast_radius",
    "corvus_dependency_chain",
    "corvus_expiring_cis",
    "corvus_correlated_gpu",
    "corvus_graph_stats",
    "corvus_triage",
    "corvus_check_target",
    "corvus_create_incident",
    "corvus_list_incidents",
    "corvus_emit_event",
    "corvus_watch_events",
    "corvus_get_context",
    "corvus_create_change",
    "corvus_get_service",
    "corvus_list_services",
    "corvus_config_drift",
    "corvus_discovery_bootstrap",
    "corvus_discovery_coverage",
    # Layer 2
    "corvus_observe_connections",
    "corvus_list_connections",
    "corvus_collect_connections",
    # Layers 4-6
    "corvus_report_dependency",
    "corvus_run_inference",
    "corvus_list_suggestions",
    "corvus_validate_suggestion",
    "corvus_report_knowledge",
    # Step execution (async triage)
    "corvus_pending_steps",
    "corvus_submit_step",
    "corvus_async_triage",
    "corvus_continue_triage",
    # Gaps / Blind Spots
    "corvus_gap_summary",
    "corvus_gap_sweep",
    # Cleanup
    "corvus_cleanup",
    # Knowledge
    "corvus_knowledge_search",
    "corvus_knowledge_add",
    # Compliance
    "corvus_compliance_audit",
}


def test_36_tools_defined():
    """Exactly 36 tool definitions exist."""
    assert len(TOOL_DEFINITIONS) == 36


def test_all_expected_tools_present():
    """Every expected tool name appears in TOOL_DEFINITIONS."""
    names = {t.name for t in TOOL_DEFINITIONS}
    assert names == EXPECTED_TOOLS


def test_all_tools_have_descriptions():
    """Every tool has a non-empty description."""
    for tool in TOOL_DEFINITIONS:
        assert tool.description, f"{tool.name} has no description"


def test_all_tools_have_input_schema():
    """Every tool has a valid JSON Schema."""
    for tool in TOOL_DEFINITIONS:
        assert tool.inputSchema, f"{tool.name} has no inputSchema"
        assert tool.inputSchema.get("type") == "object", f"{tool.name} inputSchema type is not 'object'"


def test_required_params_are_properties():
    """Every required param is also listed in properties."""
    for tool in TOOL_DEFINITIONS:
        required = tool.inputSchema.get("required", [])
        properties = tool.inputSchema.get("properties", {})
        for param in required:
            assert param in properties, f"{tool.name}: required param '{param}' not in properties"


# ---------------------------------------------------------------------------
# Tool dispatch (via internal ASGI client)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_check_target_dispatch(client):
    """corvus_check_target returns a valid response through the ASGI client."""
    import json

    result = await _dispatch_tool("corvus_check_target", {"target": "nonexistent"})
    data = json.loads(result)
    # Should return a status (might be GO since target has no events)
    assert "recommendation" in data or "status" in data or "error" in data


@pytest.mark.asyncio
async def test_emit_event_dispatch(client):
    """corvus_emit_event creates an event through the ASGI client."""
    import json

    result = await _dispatch_tool(
        "corvus_emit_event",
        {
            "source": "test",
            "type": "test.event",
            "target": "test-target",
            "severity": "info",
            "data": {"test": True},
        },
    )
    data = json.loads(result)
    assert "id" in data, f"Expected event ID in response: {data}"


@pytest.mark.asyncio
async def test_create_incident_dispatch(client):
    """corvus_create_incident creates an incident through the ASGI client."""
    import json

    result = await _dispatch_tool(
        "corvus_create_incident",
        {
            "target": "test-service",
            "title": "Test incident from MCP",
            "description": "Testing MCP endpoint",
            "severity": "warning",
            "detected_by": "test",
        },
    )
    data = json.loads(result)
    assert "id" in data, f"Expected incident ID in response: {data}"


@pytest.mark.asyncio
async def test_list_incidents_dispatch(client):
    """corvus_list_incidents returns a list."""
    import json

    result = await _dispatch_tool("corvus_list_incidents", {})
    data = json.loads(result)
    # Should be a list or contain items
    assert isinstance(data, (list, dict))


@pytest.mark.asyncio
async def test_watch_events_dispatch(client):
    """corvus_watch_events returns events."""
    import json

    result = await _dispatch_tool("corvus_watch_events", {"limit": 10})
    data = json.loads(result)
    assert isinstance(data, (list, dict))


@pytest.mark.asyncio
async def test_get_context_dispatch(client):
    """corvus_get_context returns session context."""
    import json

    result = await _dispatch_tool("corvus_get_context", {})
    data = json.loads(result)
    assert isinstance(data, (list, dict))


@pytest.mark.asyncio
async def test_create_change_dispatch(client):
    """corvus_create_change creates a change window."""
    import json

    result = await _dispatch_tool(
        "corvus_create_change",
        {
            "targets": ["test-service"],
            "description": "Test change from MCP",
            "operator": "test",
        },
    )
    data = json.loads(result)
    assert "id" in data, f"Expected change ID in response: {data}"


@pytest.mark.asyncio
async def test_list_services_dispatch(client):
    """corvus_list_services returns services from CMDB."""
    import json

    result = await _dispatch_tool("corvus_list_services", {})
    data = json.loads(result)
    assert isinstance(data, (list, dict))


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(client):
    """Unknown tool name returns error, does not raise."""
    import json

    result = await _dispatch_tool("nonexistent_tool", {})
    data = json.loads(result)
    assert "error" in data


@pytest.mark.asyncio
async def test_call_tool_handler_returns_text_content(client):
    """The call_tool handler wraps results in TextContent."""
    contents = await call_tool("corvus_get_context", {})
    assert len(contents) == 1
    assert contents[0].type == "text"
    assert len(contents[0].text) > 0


# ---------------------------------------------------------------------------
# SSE mount verification
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mcp_sse_endpoint_exists(client):
    """The /mcp/sse endpoint is mounted and reachable."""
    # SSE endpoint should return 200 with event-stream content type
    # but since we're using a test client that doesn't hold the connection,
    # we just verify the route exists by checking it doesn't 404
    resp = await client.get("/mcp/sse")
    # SSE endpoints typically return 200 or may error differently than 404
    assert resp.status_code != 404, f"MCP SSE endpoint not mounted (got {resp.status_code})"
