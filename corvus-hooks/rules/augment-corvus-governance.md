# Corvus Operational Governance — Augment

> Place this file at `.augment/rules/corvus-governance.md` in your repository.

You are working on infrastructure managed by the Corvus operational intelligence
platform. These governance rules are MANDATORY.

## Pre-Action Conflict Check

Before ANY destructive action (container restart/stop/rm, config changes,
deployments), check Corvus: `corvus_check_target(target="<service>")`.

- GO → proceed | CAUTION → state finding, proceed | STOP → ask user first

## Event Emission

After every state-changing action, emit via `corvus_emit_event`:
- restart → `remediation.restart` | stop → `remediation.stop`
- deploy/merge → `change.completed` | change window → `change.started`
- investigating → `incident.investigating` | resolved → `incident.resolved`

## Incident Workflow (user reports broken/down/failing)

1. Create incident record FIRST (before investigating)
2. Check conflicts → Investigate → Max 2 restarts → Escalate
3. Emit events for every action

## Change Lifecycle (user wants to modify infrastructure)

1. Design with risk assessment → CHECKPOINT for approval
2. Create change window → Implement via GitOps → change.completed
3. Monitor 24-72h

## Design Workflow (user wants new infrastructure)

1. Propose design → Challenge for failure modes → CHECKPOINT
2. Implement via GitOps only after approval

## GitOps Policy

ALL config changes through Git. No SSH config edits. Restarts/logs via SSH OK.

## MCP Access

Corvus: `http://your-corvus-host:9420/mcp/sse`
LiteLLM (all tools): `http://your-litellm-host:4000/mcp/sse`
