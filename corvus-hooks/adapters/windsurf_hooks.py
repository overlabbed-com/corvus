#!/usr/bin/env python3
"""Corvus Governance Adapter — Windsurf (Codeium).

Windsurf uses a rules-based system with Cascade flows. It supports:
  - .windsurfrules (project-level rules)
  - Global rules in Windsurf settings

For structural enforcement, Windsurf supports MCP servers. Corvus MCP tools
are already available fleet-wide via LiteLLM proxy. This adapter provides
a companion pre-check script that can be invoked from Windsurf's terminal
or integrated via MCP tool wrappers.

Usage as a standalone pre-check (from terminal or shell integration):
  python3 ~/.claude/hooks/adapters/windsurf_hooks.py check <target>
  python3 ~/.claude/hooks/adapters/windsurf_hooks.py classify "<prompt>"
  python3 ~/.claude/hooks/adapters/windsurf_hooks.py emit <event_type> <target>

Exit codes:
  0 = GO or CAUTION (proceed)
  2 = STOP (blocked)
  1 = usage error

Windsurf MCP integration:
  Add to Windsurf's MCP config (settings or .windsurfrules):
  {
    "mcpServers": {
      "corvus": {
        "command": "npx",
        "args": ["-y", "@anthropic/litellm-mcp-proxy"],
        "env": {
          "LITELLM_BASE_URL": "http://192.168.20.14:4000",
          "LITELLM_API_KEY": "<your-key>"
        }
      }
    }
  }

  Or use the direct Corvus MCP endpoint if available.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import corvus_core as core

SOURCE = "windsurf"


def cmd_check(target: str):
    """Check a target against Corvus governance."""
    api_key = core.get_api_key()
    if not api_key:
        print("Warning: Corvus API key not configured.", file=sys.stderr)
        sys.exit(0)

    result = core.check_target(target, api_key)
    if result is None:
        print(f"Warning: Corvus unreachable at {core.CORVUS_BASE_URL}.", file=sys.stderr)
        sys.exit(0)

    rec = result.get("recommendation", "GO")
    reason = result.get("reason", "")
    incidents = len(result.get("active_incidents", []))
    changes = len(result.get("active_changes", []))

    if rec == "STOP":
        print(
            f"BLOCKED by Corvus governance — target: {target}\n"
            f"Reason: {reason}\n"
            f"Active incidents: {incidents}, Active changes: {changes}\n"
            f"Resolve the conflict before retrying.",
            file=sys.stderr,
        )
        sys.exit(2)

    if rec == "CAUTION":
        print(
            f"CAUTION from Corvus — target: {target}\n"
            f"Reason: {reason}\n"
            f"Active incidents: {incidents}, Active changes: {changes}",
            file=sys.stderr,
        )

    # Output JSON for programmatic consumers
    print(json.dumps({"recommendation": rec, "reason": reason, "target": target}))
    sys.exit(0)


def cmd_classify(prompt: str):
    """Classify user intent and output governance mandate."""
    intent = core.classify_intent(prompt)
    output = {"intent": intent or "neutral"}

    if intent == "incident":
        output["mandate"] = core.INCIDENT_MANDATE
    elif intent == "change":
        output["mandate"] = core.CHANGE_MANDATE
    elif intent == "design":
        output["mandate"] = core.DESIGN_MANDATE

    print(json.dumps(output))

    # Also print mandate to stderr for terminal visibility
    if intent and intent != "neutral":
        mandate = output.get("mandate", "")
        if mandate:
            print(f"\n[CORVUS {intent.upper()} WORKFLOW]\n{mandate}", file=sys.stderr)

    sys.exit(0)


def cmd_emit(event_type: str, target: str):
    """Emit a Corvus event."""
    if core.emit_event(event_type, target, source=SOURCE):
        print(json.dumps({"status": "emitted", "event_type": event_type, "target": target}))
        print(f"Corvus: {event_type} -> {target}", file=sys.stderr)
    else:
        print(json.dumps({"status": "failed", "event_type": event_type, "target": target}))
        print("Warning: Failed to emit Corvus event.", file=sys.stderr)
    sys.exit(0)


def cmd_stdin_check():
    """Read JSON from stdin (for pipe-based integration)."""
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    # Support both command-style and tool-style input
    command = data.get("command", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    target = None  # type: Optional[str]

    if command:
        target = core.extract_target_from_command(command)
    elif tool_name and core.is_destructive_mcp_tool(tool_name):
        target = core.extract_target_from_mcp(tool_name, tool_input)

    if not target:
        sys.exit(0)

    api_key = core.get_api_key()
    if not api_key:
        sys.exit(0)

    result = core.check_target(target, api_key)
    if result is None:
        sys.exit(0)

    rec = result.get("recommendation", "GO")
    if rec == "STOP":
        reason = result.get("reason", "")
        print(f"BLOCKED: {target} — {reason}", file=sys.stderr)
        sys.exit(2)

    if rec == "CAUTION":
        reason = result.get("reason", "")
        print(f"CAUTION: {target} — {reason}", file=sys.stderr)

    sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  windsurf_hooks.py check <target>\n"
            "  windsurf_hooks.py classify \"<prompt>\"\n"
            "  windsurf_hooks.py emit <event_type> <target>\n"
            "  windsurf_hooks.py stdin-check  (reads JSON from stdin)",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "check" and len(sys.argv) >= 3:
        cmd_check(sys.argv[2])
    elif mode == "classify" and len(sys.argv) >= 3:
        cmd_classify(sys.argv[2])
    elif mode == "emit" and len(sys.argv) >= 4:
        cmd_emit(sys.argv[2], sys.argv[3])
    elif mode == "stdin-check":
        cmd_stdin_check()
    else:
        print(f"Unknown mode or missing args: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
