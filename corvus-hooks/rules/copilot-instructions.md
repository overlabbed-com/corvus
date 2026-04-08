# Corvus Operational Governance — GitHub Copilot

> Place this file at `.github/copilot-instructions.md` in your repository.

You are working on infrastructure managed by the Corvus operational intelligence
platform. These governance rules are MANDATORY for all infrastructure operations.

## Pre-Action Conflict Check (MANDATORY)

Before ANY destructive action on infrastructure (container restart/stop/rm/kill,
config changes, deployments, secret rotation), you MUST check Corvus for
conflicts. Use the Corvus MCP tools if available, or call the REST API:

```bash
curl -s "http://192.168.20.14:9420/ops/events/targets/<target>/status" \
  -H "Authorization: Bearer $CORVUS_API_KEY"
```

- **GO**: Proceed normally
- **CAUTION**: State finding, proceed carefully
- **STOP**: Do NOT act — ask the user

## Event Emission (MANDATORY)

After every state-changing action, emit a Corvus event:

```bash
curl -s -X POST "http://192.168.20.14:9420/ops/events" \
  -H "Authorization: Bearer $CORVUS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type":"<event_type>","target":"<service>","source":"copilot","severity":"info"}'
```

Event types: `remediation.restart`, `remediation.stop`, `change.started`,
`change.completed`, `incident.investigating`, `incident.resolved`

## Incident Workflow

When the user reports something broken/down/failing:
1. CREATE incident record FIRST (before investigating)
2. Check for conflicts
3. Investigate (logs, status)
4. Max 2 restart attempts, then escalate
5. Emit events for every action
6. Update incident on resolution

## Change Lifecycle

When the user wants to install/deploy/configure:
1. Design the change with risk assessment
2. Create change window (`change.started`)
3. Present design for approval (CHECKPOINT)
4. Implement via GitOps (branch + PR) only after approval
5. Emit `change.completed` after deployment

## Design Workflow

When the user wants to build/create new infrastructure:
1. Research and propose (don't ask user to decide)
2. Challenge the design for failure modes
3. Present design + challenge (CHECKPOINT)
4. Implement via GitOps only after approval

## GitOps Policy

ALL infrastructure config changes go through Git. No SSH config edits.
Emergency restarts and log checks via SSH are acceptable.
