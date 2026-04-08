# Corvus Operational Governance — Aider

> Place this file at `CONVENTIONS.md` in your project root for Aider to read.

## Corvus Integration

This project's infrastructure is managed by the Corvus operational intelligence
platform. When making infrastructure changes, follow these mandatory rules.

## Pre-Action Conflict Check

Before ANY destructive action (container restart/stop/rm, config changes,
deployments), check Corvus for conflicts:

```bash
curl -s "http://your-corvus-host:9420/ops/events/targets/<target>/status" \
  -H "Authorization: Bearer $CORVUS_API_KEY" \
  -H "Accept: application/json"
```

Response `recommendation` field: GO (proceed), CAUTION (proceed carefully),
STOP (do not act without operator approval).

## Event Emission

After every state-changing action, emit an event:

```bash
curl -s -X POST "http://your-corvus-host:9420/ops/events" \
  -H "Authorization: Bearer $CORVUS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type":"<type>","target":"<service>","source":"aider","severity":"info"}'
```

Types: remediation.restart, remediation.stop, change.started, change.completed,
incident.investigating, incident.resolved

## Workflows

- **Incident** (broken/down/failing): Create incident first, then investigate.
  Max 2 restarts, then escalate.
- **Change** (install/deploy/configure): Design first, get approval, then
  implement via GitOps (branch + PR). No direct SSH config edits.
- **Design** (build/create new): Propose design with risk assessment, challenge
  for failure modes, get approval before implementing.

## GitOps Policy

ALL infrastructure config changes go through Git. No SSH config edits.
Emergency restarts and log checks via SSH are acceptable.
