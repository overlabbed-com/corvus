#!/usr/bin/env python3
"""Corvus Governance Adapter — OpenAI Codex CLI.

Codex CLI hooks use the same stdin JSON model as Claude Code:
  - PreToolUse: receives {tool_name, tool_input, session_id, ...}
  - PostToolUse: receives {tool_name, tool_input, tool_result, session_id, ...}
  - UserPromptSubmit: receives {user_prompt, session_id, ...}

Exit codes: 0 = allow, 2 = block (PreToolUse only).
Stderr output is shown to the model as context.

Codex hook config goes in ~/.codex/config.toml:

  [hooks.PreToolUse]
  matcher = "shell|Bash"
  command = "python3 ~/.claude/hooks/adapters/codex_hooks.py pre-tool"
  timeout = 10

  [hooks.PostToolUse]
  matcher = "shell|Bash"
  command = "python3 ~/.claude/hooks/adapters/codex_hooks.py post-tool"
  timeout = 10

  [hooks.UserPromptSubmit]
  command = "python3 ~/.claude/hooks/adapters/codex_hooks.py user-prompt"
  timeout = 5
"""

from __future__ import annotations

import json
import os
import sys


# Add parent dir to path for corvus_core import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import corvus_core as core

SOURCE = "codex-cli"


def handle_pre_tool():
    """PreToolUse: check Corvus for conflicts before destructive actions."""
    data = json.loads(sys.stdin.read())
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Shell/Bash commands
    if tool_name.lower() in ("shell", "bash"):
        command = tool_input.get("command", "") or tool_input.get("cmd", "")
        target = core.extract_target_from_command(command)
        if target is None:
            sys.exit(0)
    elif core.is_destructive_mcp_tool(tool_name):
        target = core.extract_target_from_mcp(tool_name, tool_input)
    else:
        sys.exit(0)

    if not target:
        sys.exit(0)

    api_key = core.get_api_key()
    if not api_key:
        print("Warning: Corvus API key not configured. Skipping governance check.", file=sys.stderr)
        sys.exit(0)

    result = core.check_target(target, api_key)
    if result is None:
        print(f"Warning: Corvus unreachable at {core.CORVUS_BASE_URL}. Proceeding without check.", file=sys.stderr)
        sys.exit(0)

    rec = result.get("recommendation", "GO")
    reason = result.get("reason", "")

    if rec == "STOP":
        print(
            f"BLOCKED by Corvus governance — target: {target}\n"
            f"Reason: {reason}\n"
            f"Active incidents: {len(result.get('active_incidents', []))}\n"
            f"Active changes: {len(result.get('active_changes', []))}\n"
            f"Resolve the conflict before retrying.",
            file=sys.stderr,
        )
        sys.exit(2)

    if rec == "CAUTION":
        print(
            f"CAUTION from Corvus — target: {target}\n"
            f"Reason: {reason}\n"
            f"Proceeding, but be aware of activity on this target.",
            file=sys.stderr,
        )

    sys.exit(0)


def handle_post_tool():
    """PostToolUse: auto-emit Corvus events for destructive actions."""
    data = json.loads(sys.stdin.read())
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", "")

    if isinstance(tool_result, str) and any(
        kw in tool_result.lower() for kw in ["error", "failed", "not found", "permission denied"]
    ):
        sys.exit(0)

    event_type = None
    target = None

    if tool_name.lower() in ("shell", "bash"):
        command = tool_input.get("command", "") or tool_input.get("cmd", "")
        extracted = core.extract_action_from_command(command)
        if not extracted:
            sys.exit(0)
        action, target = extracted
        event_type = core.ACTION_EVENT_MAP.get(action)
    elif core.is_destructive_mcp_tool(tool_name):
        event_type = core.get_mcp_event_type(tool_name)
        target = core.extract_target_from_mcp(tool_name, tool_input)

    if event_type and target:
        if core.emit_event(event_type, target, source=SOURCE):
            print(f"Corvus: {event_type} -> {target}", file=sys.stderr)

    sys.exit(0)


def handle_user_prompt():
    """UserPromptSubmit: classify intent and inject governance mandates."""
    data = json.loads(sys.stdin.read())
    prompt = data.get("user_prompt", "")
    if not prompt:
        sys.exit(0)

    intent = core.classify_intent(prompt)
    if intent == "incident":
        print(f"[CORVUS INCIDENT WORKFLOW]\n{core.INCIDENT_MANDATE}", file=sys.stderr)
    elif intent == "change":
        print(f"[CORVUS CHANGE LIFECYCLE]\n{core.CHANGE_MANDATE}", file=sys.stderr)
    elif intent == "design":
        print(f"[CORVUS DESIGN WORKFLOW]\n{core.DESIGN_MANDATE}", file=sys.stderr)

    sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print("Usage: codex_hooks.py <pre-tool|post-tool|user-prompt>", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    try:
        if mode == "pre-tool":
            handle_pre_tool()
        elif mode == "post-tool":
            handle_post_tool()
        elif mode == "user-prompt":
            handle_user_prompt()
        else:
            print(f"Unknown mode: {mode}", file=sys.stderr)
            sys.exit(1)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)


if __name__ == "__main__":
    main()
