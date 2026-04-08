#!/usr/bin/env python3
"""Corvus Lifecycle Enforcement Hook — Claude Code UserPromptSubmit.

Classifies user intent from natural language and injects MANDATORY governance
instructions into the conversation. Runs at the harness level — Claude cannot
skip or rationalize around these instructions.

Intent classification:
  - Incident: "X is broken/down/failing" -> inject incident creation mandate
  - Change: "install/deploy/add/configure X" -> inject change lifecycle mandate
  - Design: "build/create new X" -> inject full Architect workflow mandate
  - Neutral: no infra context -> silent pass-through

Exit code is ALWAYS 0 (never block user prompts). Governance is injected via stderr.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corvus_core as core

# CC-specific formatted mandates (with box-drawing borders for visibility)
INCIDENT_MANDATE_CC = """
CORVUS GOVERNANCE — INCIDENT WORKFLOW ACTIVATED

The user's request indicates an infrastructure issue. You MUST follow
the Incident Workflow (governance.md). These steps are NON-NEGOTIABLE:

1. SWITCH to Responder role — announce the role switch
2. CREATE Corvus incident IMMEDIATELY — before any investigation:
   corvus_create_incident(target="<service>", title="<short title>",
     description="<what the user reported>", severity="warning",
     detected_by="claude-code")
3. CHECK for conflicts: corvus_check_target(target="<service>")
4. INVESTIGATE — check logs, status, dependencies
5. If restart needed: MAX 2 attempts, then escalate to the operator
6. EMIT events for every action: corvus_emit_event(...)
7. When resolved: update the incident and emit resolution event

DO NOT skip the incident creation. DO NOT investigate before creating
the record. The incident record is the FIRST action, always.
""".strip()

CHANGE_MANDATE_CC = """
CORVUS GOVERNANCE — CHANGE LIFECYCLE ACTIVATED

The user's request involves infrastructure modification. You MUST
follow the Standard Workflow (governance.md). These steps are
NON-NEGOTIABLE:

1. SWITCH to Architect role — design the change
2. CREATE Corvus change window BEFORE any modification:
   corvus_emit_event(type="change.started", target="<service>",
     source="claude-code", data={"description": "..."})
3. Architect design -> Lean Review -> Advocate challenge
4. CHECKPOINT — present design + challenge to the operator for approval
5. ONLY after the operator approves: Changemaker creates branch + MR
6. GitOps ONLY — no SSH config edits, no cowboy changes
7. After deployment: corvus_emit_event(type="change.completed", ...)
8. Sentinel monitors for 24-72h

DO NOT modify infrastructure before the design is approved.
DO NOT skip the Architect -> Advocate -> CHECKPOINT gates.
""".strip()

DESIGN_MANDATE_CC = """
CORVUS GOVERNANCE — DESIGN WORKFLOW ACTIVATED

The user's request involves creating new infrastructure. You MUST
follow the full Standard Workflow (governance.md):

1. Create project directory if needed (project gate)
2. Architect designs — research and PROPOSE (don't ask the operator to decide)
3. Design MUST include: problem statement, proposed solution, risk
   assessment, rollback plan, dependency map, phased rollout
4. Lean Review — simplest solution? YAGNI? Existing code?
5. Advocate challenges the design (MANDATORY, no exceptions)
6. CHECKPOINT — present BOTH design + challenge to the operator
7. Only after approval: Changemaker implements via GitOps

DO NOT implement before designing. DO NOT present a design without
the Advocate challenge. DO NOT skip the CHECKPOINT.
""".strip()


def main():
    """Main hook entry point."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    prompt = data.get("user_prompt", "")
    if not prompt:
        sys.exit(0)

    intent = core.classify_intent(prompt)

    if intent == "incident":
        print(INCIDENT_MANDATE_CC, file=sys.stderr)
    elif intent == "change":
        print(CHANGE_MANDATE_CC, file=sys.stderr)
    elif intent == "design":
        print(DESIGN_MANDATE_CC, file=sys.stderr)

    # Always exit 0 — never block user prompts
    sys.exit(0)


if __name__ == "__main__":
    main()
