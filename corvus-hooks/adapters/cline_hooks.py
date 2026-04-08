#!/usr/bin/env python3
"""Corvus Governance Adapter — Cline (VS Code extension).

Cline hooks receive JSON on stdin and return JSON on stdout:
  Input:  {taskId, hookName, clineVersion, timestamp, workspaceRoots, model, ...}
  Output: {cancel: bool, contextModification: string, errorMessage: string}

For PreToolUse, additional fields: {toolName, toolInput}
For PostToolUse, additional fields: {toolName, toolInput, toolResult}
For UserPromptSubmit, additional fields: {userPrompt}

Hook locations:
  Global: ~/Documents/Cline/Hooks/
  Project: .clinerules/hooks/

To install globally:
  mkdir -p ~/Documents/Cline/Hooks
  ln -s ~/.claude/hooks/adapters/cline_hooks.py ~/Documents/Cline/Hooks/corvus-governance.py

To install per-project:
  mkdir -p .clinerules/hooks
  ln -s ~/.claude/hooks/adapters/cline_hooks.py .clinerules/hooks/corvus-governance.py

Hook config in .clinerules/hooks/hooks.json:
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "execute_command|write_to_file|replace_in_file",
      "hooks": [{"type": "command", "command": "python3 .clinerules/hooks/corvus-governance.py pre-tool"}]
    }],
    "PostToolUse": [{
      "matcher": "execute_command",
      "hooks": [{"type": "command", "command": "python3 .clinerules/hooks/corvus-governance.py post-tool"}]
    }],
    "UserPromptSubmit": [{
      "hooks": [{"type": "command", "command": "python3 .clinerules/hooks/corvus-governance.py user-prompt"}]
    }]
  }
}
"""

from __future__ import annotations

import json
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import corvus_core as core

SOURCE = "cline"


def respond(cancel: bool = False, context: str = "", error: str = ""):
    """Output Cline hook response JSON and exit."""
    resp = {}  # type: Dict[str, Any]
    if cancel:
        resp["cancel"] = True
    if context:
        resp["contextModification"] = context
    if error:
        resp["errorMessage"] = error
    if resp:
        print(json.dumps(resp))
    sys.exit(0)


def handle_pre_tool():
    """PreToolUse: check Corvus for conflicts."""
    data = json.loads(sys.stdin.read())
    tool_name = data.get("toolName", "")
    tool_input = data.get("toolInput", {})

    # Cline uses execute_command for shell commands
    if tool_name == "execute_command":
        command = tool_input.get("command", "")
        target = core.extract_target_from_command(command)
        if target is None:
            respond()
            return
    elif core.is_destructive_mcp_tool(tool_name):
        target = core.extract_target_from_mcp(tool_name, tool_input)
    else:
        respond()
        return

    if not target:
        respond()
        return

    api_key = core.get_api_key()
    if not api_key:
        respond(context="[Corvus] API key not configured. Governance check skipped.")
        return

    result = core.check_target(target, api_key)
    if result is None:
        respond(context=f"[Corvus] Unreachable at {core.CORVUS_BASE_URL}. Governance check skipped.")
        return

    rec = result.get("recommendation", "GO")
    reason = result.get("reason", "")
    changes = len(result.get("active_changes", []))
    incidents = len(result.get("active_incidents", []))

    if rec == "STOP":
        respond(
            cancel=True,
            error=(
                f"CORVUS GOVERNANCE BLOCK — target: {target}\n"
                f"Reason: {reason}\n"
                f"Active incidents: {incidents}, Active changes: {changes}\n"
                f"Resolve the conflict before retrying."
            ),
        )
        return

    if rec == "CAUTION":
        respond(
            context=(
                f"[Corvus CAUTION] target: {target} — {reason}\n"
                f"Active incidents: {incidents}, Active changes: {changes}\n"
                f"Proceeding, but be aware of activity on this target."
            ),
        )
        return

    respond()


def handle_post_tool():
    """PostToolUse: auto-emit Corvus events."""
    data = json.loads(sys.stdin.read())
    tool_name = data.get("toolName", "")
    tool_input = data.get("toolInput", {})
    tool_result = data.get("toolResult", "")

    if isinstance(tool_result, str) and any(
        kw in tool_result.lower() for kw in ["error", "failed", "not found"]
    ):
        respond()
        return

    event_type = None
    target = None

    if tool_name == "execute_command":
        command = tool_input.get("command", "")
        extracted = core.extract_action_from_command(command)
        if not extracted:
            respond()
            return
        action, target = extracted
        event_type = core.ACTION_EVENT_MAP.get(action)
    elif core.is_destructive_mcp_tool(tool_name):
        event_type = core.get_mcp_event_type(tool_name)
        target = core.extract_target_from_mcp(tool_name, tool_input)

    if event_type and target:
        if core.emit_event(event_type, target, source=SOURCE):
            respond(context=f"[Corvus] Event emitted: {event_type} -> {target}")
            return

    respond()


def handle_user_prompt():
    """UserPromptSubmit: classify intent and inject governance."""
    data = json.loads(sys.stdin.read())
    prompt = data.get("userPrompt", "")
    if not prompt:
        respond()
        return

    intent = core.classify_intent(prompt)
    if intent == "incident":
        respond(context=f"[CORVUS INCIDENT WORKFLOW]\n{core.INCIDENT_MANDATE}")
    elif intent == "change":
        respond(context=f"[CORVUS CHANGE LIFECYCLE]\n{core.CHANGE_MANDATE}")
    elif intent == "design":
        respond(context=f"[CORVUS DESIGN WORKFLOW]\n{core.DESIGN_MANDATE}")
    else:
        respond()


def main():
    if len(sys.argv) < 2:
        print("Usage: cline_hooks.py <pre-tool|post-tool|user-prompt>", file=sys.stderr)
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
        respond()


if __name__ == "__main__":
    main()
