"""Tests for MCP server tools — verifies tool registration and schemas."""

from src.mcp_server import mcp


def test_mcp_tools_registered():
    """Verify all 20 expected tools are registered."""
    tools = mcp._tool_manager._tools
    expected = {
        "ops_check_target",
        "ops_watch_events",
        "ops_emit_event",
        "ops_create_incident",
        "ops_create_change",
        "ops_close_change",
        "ops_get_context",
        "ops_list_services",
        "ops_register_service",
        "ops_run_triage",
        "ops_get_metrics",
        "ops_report_gap",
        "ops_create_plan",
        "ops_approve_plan",
        "ops_execute_plan",
        "ops_plan_status",
        "ops_pull_ready_steps",
        "ops_report_step_result",
        "ops_cancel_plan",
        "ops_rollback_plan",
    }
    assert expected == set(tools.keys()), (
        f"Missing: {expected - set(tools.keys())}, Extra: {set(tools.keys()) - expected}"
    )


def test_ops_check_target_schema():
    tool = mcp._tool_manager._tools["ops_check_target"]
    assert "GO/CAUTION/STOP" in tool.description


def test_ops_emit_event_schema():
    tool = mcp._tool_manager._tools["ops_emit_event"]
    assert "state-changing" in tool.description


def test_ops_create_change_schema():
    tool = mcp._tool_manager._tools["ops_create_change"]
    assert "change window" in tool.description.lower()


def test_ops_run_triage_schema():
    tool = mcp._tool_manager._tools["ops_run_triage"]
    assert "FMEA" in tool.description


def test_ops_report_gap_schema():
    tool = mcp._tool_manager._tools["ops_report_gap"]
    assert "blind spot" in tool.description.lower()


def test_ops_create_plan_schema():
    tool = mcp._tool_manager._tools["ops_create_plan"]
    assert "DAG-ordered" in tool.description


def test_ops_approve_plan_schema():
    tool = mcp._tool_manager._tools["ops_approve_plan"]
    assert "trust ledger" in tool.description.lower()


def test_ops_execute_plan_schema():
    tool = mcp._tool_manager._tools["ops_execute_plan"]
    assert "change window" in tool.description.lower()


def test_ops_plan_status_schema():
    tool = mcp._tool_manager._tools["ops_plan_status"]
    assert "progress" in tool.description.lower()


def test_ops_pull_ready_steps_schema():
    tool = mcp._tool_manager._tools["ops_pull_ready_steps"]
    assert "dependencies" in tool.description.lower()


def test_ops_report_step_result_schema():
    tool = mcp._tool_manager._tools["ops_report_step_result"]
    assert "failure_policy" in tool.description


def test_ops_cancel_plan_schema():
    tool = mcp._tool_manager._tools["ops_cancel_plan"]
    assert "cancel" in tool.description.lower()


def test_ops_rollback_plan_schema():
    tool = mcp._tool_manager._tools["ops_rollback_plan"]
    assert "reverse" in tool.description.lower()
