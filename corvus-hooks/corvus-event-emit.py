#!/usr/bin/env python3
"""Corvus Event Emission Hook — Claude Code PostToolUse.

Automatically emits Corvus events after destructive infrastructure actions
complete. Ensures every state-changing action is recorded in the operational
timeline without relying on Claude remembering to emit events manually.

Runs after tool execution. Always exits 0 (never blocks post-execution).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corvus_core as core

SOURCE = "claude-code"


def main():
    """Main hook entry point."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", "")

    # Only emit on successful execution (no error indicators in result)
    if isinstance(tool_result, str) and any(
        kw in tool_result.lower()
        for kw in ["error", "failed", "not found", "permission denied"]
    ):
        sys.exit(0)

    event_type = None
    target = None

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        extracted = core.extract_action_from_command(command)
        if extracted is None:
            sys.exit(0)
        action, target = extracted
        event_type = core.ACTION_EVENT_MAP.get(action)
    elif core.is_destructive_mcp_tool(tool_name):
        event_type = core.get_mcp_event_type(tool_name)
        target = core.extract_target_from_mcp(tool_name, tool_input)

    if not event_type or not target:
        sys.exit(0)

    if core.emit_event(event_type, target, source=SOURCE):
        print(
            f"Corvus event emitted: {event_type} -> {target}",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
