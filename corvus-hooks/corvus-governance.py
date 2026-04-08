#!/usr/bin/env python3
"""Corvus Governance Enforcement Hook — Claude Code PreToolUse.

Intercepts destructive infrastructure actions and checks Corvus for active
change windows, incidents, or conflicts before allowing execution.
Runs at the harness level — outside the model's control.

Exit codes:
  0 = Allow (tool proceeds; stderr message shown as context if CAUTION)
  2 = Block (tool call denied; stderr message shown to Claude)

Fail-open: if Corvus is unreachable, allow the action with a warning.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corvus_core as core


def main():
    """Main hook entry point."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # --- Extract target based on tool type ---
    target = None

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        target = core.extract_target_from_command(command)
        if target is None:
            sys.exit(0)
    elif core.is_destructive_mcp_tool(tool_name):
        target = core.extract_target_from_mcp(tool_name, tool_input)
    else:
        sys.exit(0)

    if not target:
        print(
            f"Warning: Corvus governance: could not extract target from {tool_name} call. "
            "Proceeding without conflict check.",
            file=sys.stderr,
        )
        sys.exit(0)

    # --- Get API key ---
    api_key = core.get_api_key()
    if not api_key:
        print(
            f"Warning: Corvus governance: API key not found "
            f"({core.KEYCHAIN_SERVICE}/{core.KEYCHAIN_ACCOUNT}). "
            "Proceeding without conflict check.",
            file=sys.stderr,
        )
        sys.exit(0)

    # --- Call Corvus check_target ---
    result = core.check_target(target, api_key)

    if result is None:
        print(
            f"Warning: Corvus governance: could not reach Corvus at {core.CORVUS_BASE_URL}. "
            "Proceeding without conflict check.",
            file=sys.stderr,
        )
        sys.exit(0)

    recommendation = result.get("recommendation", "GO")
    reason = result.get("reason", "")
    active_changes = result.get("active_changes", [])
    active_incidents = result.get("active_incidents", [])

    # --- Decide ---
    if recommendation == "STOP":
        print(
            f"CORVUS GOVERNANCE BLOCK — target: {target}\n"
            f"   Recommendation: STOP\n"
            f"   Reason: {reason}\n"
            f"   Active changes: {len(active_changes)}\n"
            f"   Active incidents: {len(active_incidents)}\n"
            f"\n"
            f"   This action has been BLOCKED by the Corvus governance hook.\n"
            f"   There is an active critical incident or conflicting change window\n"
            f"   on this target. Resolve the conflict before retrying.\n"
            f"   Ask the operator if you believe this is incorrect.",
            file=sys.stderr,
        )
        sys.exit(2)

    if recommendation == "CAUTION":
        print(
            f"CORVUS GOVERNANCE CAUTION — target: {target}\n"
            f"   Recommendation: CAUTION\n"
            f"   Reason: {reason}\n"
            f"   Active changes: {len(active_changes)}\n"
            f"   Active incidents: {len(active_incidents)}\n"
            f"\n"
            f"   Proceeding, but be aware of the above activity on this target.",
            file=sys.stderr,
        )
        sys.exit(0)

    # GO — silent allow
    sys.exit(0)


if __name__ == "__main__":
    main()
