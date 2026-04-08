# Corvus Operational Governance

> This file is read by: Cline, Augment, Codex CLI, Continue, and any tool
> that reads AGENTS.md from the project root. It defines mandatory operational
> governance rules for AI assistants working on this infrastructure.

## Corvus — Operational Intelligence Platform

Corvus is the operational intelligence platform that tracks all infrastructure
changes, incidents, and events. All AI assistants MUST integrate with Corvus
when performing infrastructure operations.

**Corvus MCP tools are available via LiteLLM proxy.** If your tool supports MCP,
configure the Corvus MCP server to get direct access to governance tools.

## MANDATORY: Pre-Action Conflict Check

Before ANY destructive or state-changing action on infrastructure (container
restart, config change, deployment, secret rotation), you MUST check Corvus:

```
corvus_check_target(target="<container_or_service_name>")
```

Interpret the result:
- **GO**: No conflicts. Proceed normally.
- **CAUTION**: Recent activity on this target. State what you found and why
  you're proceeding.
- **STOP**: Active change window or incident. Do NOT act — ask the operator.

If Corvus is unreachable, proceed with a warning but note the skip.

## MANDATORY: Event Emission

Emit Corvus events for ALL state-changing actions:

| Action | Event Type |
|--------|-----------|
| Restart container | `remediation.restart` |
| Stop container | `remediation.stop` |
| Remove container | `remediation.remove` |
| Kill container | `remediation.kill` |
| Start container | `remediation.start` |
| Merge PR / deploy | `change.completed` |
| Open change window | `change.started` |
| Investigate issue | `incident.investigating` |
| Resolve issue | `incident.resolved` |

```
corvus_emit_event(type="<event_type>", target="<service>",
  source="<your-tool-name>", data={"description": "..."})
```

## MANDATORY: Incident Workflow

When the user reports an infrastructure issue ("X is broken", "X is down",
"X is failing", "X is crash-looping"):

1. **CREATE incident record FIRST** — before any investigation:
   ```
   corvus_create_incident(target="<service>", title="<title>",
     description="<what user reported>", severity="warning",
     detected_by="<your-tool-name>")
   ```
2. Check for conflicts: `corvus_check_target(target="<service>")`
3. Investigate (logs, status, dependencies)
4. If restart needed: MAX 2 attempts, then escalate to operator
5. Emit events for every action taken
6. When resolved: update incident and emit resolution event

**DO NOT skip the incident creation. It is the FIRST action, always.**

## MANDATORY: Change Lifecycle

When the user requests infrastructure modification ("install X", "deploy X",
"configure X", "add X"):

1. **Design the change** — propose an approach with risk assessment
2. **Create change window** before any modification:
   ```
   corvus_emit_event(type="change.started", target="<service>",
     source="<your-tool-name>", data={"description": "..."})
   ```
3. Present design for operator approval (CHECKPOINT)
4. Only after approval: implement via GitOps (branch + PR)
5. After deployment: emit `change.completed` event
6. Monitor for 24-72h post-change

**DO NOT modify infrastructure before the design is approved.**

## MANDATORY: Design Workflow

When the user requests new infrastructure ("build X", "create new X"):

1. Research and propose a design (don't ask the operator to decide)
2. Design must include: problem statement, proposed solution, risk assessment,
   rollback plan, dependency map
3. Challenge the design — identify failure modes and edge cases
4. Present design + challenge for approval (CHECKPOINT)
5. Only after approval: implement via GitOps

**DO NOT implement before designing. DO NOT skip the challenge step.**

## GitOps Policy

ALL infrastructure changes go through Git. No exceptions.

- Docker stack changes MUST be in the GitOps repository
- Create a branch, make changes, submit a Pull Request
- NEVER SSH into a host and edit compose/env/config files directly
- Emergency troubleshooting (restart, logs, status checks) via SSH is fine
- Configuration changes are NOT fine via SSH

## Blast Radius Check

Before restarting or modifying a service, check dependencies:

```
corvus_blast_radius(service="<service_name>")
```

If downstream services would be affected, state them in your risk assessment.

## MCP Configuration

To access Corvus tools, add to your MCP configuration:

```json
{
  "mcpServers": {
    "corvus": {
      "url": "http://your-corvus-host:9420/mcp/sse"
    }
  }
}
```

Or via LiteLLM proxy (includes all fleet MCP tools):

```json
{
  "mcpServers": {
    "litellm-mcp": {
      "url": "http://your-litellm-host:4000/mcp/sse"
    }
  }
}
```
