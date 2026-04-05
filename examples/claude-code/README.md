# Claude Code — Corvus Integration (Customer Zero)

Claude Code integrates with Corvus through governance rules and MCP tools.
CC doesn't call the Corvus API directly — it uses MCP tools proxied through
LiteLLM, and governance rules enforce protocol compliance.

## Integration Points

### MCP Tools (available in every CC session)

| Tool | Purpose | Corvus Endpoint |
|------|---------|----------------|
| `ops_check_target` | Pre-action conflict check (GO/CAUTION/STOP) | GET /ops/events/targets/{target}/status |
| `ops_watch_events` | Real-time event feed from other agents | GET /ops/events |
| `ops_emit_event` | Emit operational events for CC actions | POST /ops/events |
| `ops_create_incident` | Create incident records | POST /ops/incidents |
| `ops_create_change` | Declare change windows | POST /ops/changes |
| `ops_close_change` | Close change windows | PATCH /ops/changes/{id} |
| `ops_get_context` | Session start briefing (last 24h) | GET /ops/events/context |
| `ops_list_services` | Query CMDB | GET /ops/cmdb |
| `ops_register_service` | Register services in CMDB | POST /ops/cmdb/register |

### Governance Rules

CC's governance framework (`.claude/rules/governance.md`) enforces Corvus compliance:

1. **Pre-action conflict check** — Before any MODIFY+ action on a target, CC MUST
   call `ops_check_target`. GO = proceed. CAUTION = review. STOP = ask human.

2. **Event emission** — CC MUST emit events for all state-changing actions:
   - Container restarts → `remediation.restart`
   - Investigations → `incident.investigating`
   - PR merges → `change.completed`
   - Change windows → `change.started` / `change.completed`

3. **Incident records** — CC's Responder role MUST create Corvus incident records
   when investigating infrastructure issues, not just markdown reports.

4. **Session end verification** — CC MUST verify all state-changing actions emitted events.

### Operational Protocol Task

`.claude/rules/tasks/ops-protocol.md` — loaded in every CC session. Defines:
- Shared event type taxonomy
- When to check events (role switches, checkpoints, before MODIFY actions)
- How to create incidents and emit events
- Session end compliance verification

## How CC Uses Corvus (Practical Examples)

### Before restarting a container:
```
CC calls: ops_check_target(target="litellm")
Response: {"recommendation": "STOP", "reason": "Active incident INC-042..."}
CC: "NemoClaw is already investigating litellm. I'll wait."
```

### After deploying a change:
```
CC calls: ops_emit_event(source="claude-code", type="change.completed",
          target="admin-api", data={"summary": "OCSF transformer deployed"})
→ NemoClaw sees this in its next sweep and doesn't alert on the restart
```

### During a long session:
```
CC calls: ops_watch_events(min_severity="warning")
Response: {"events": [{"type": "remediation.restart", "target": "vllm-default",
           "source": "nemoclaw"}]}
CC: "FYI — NemoClaw restarted vllm-default while we were working."
```

## Files

| File | Purpose |
|------|---------|
| `.claude/rules/governance.md` | CC governance with Corvus compliance rules |
| `.claude/rules/tasks/ops-protocol.md` | Operational protocol task procedure |
| `.claude/rules/agents/responder.md` | Responder role with SOP integration |
| `.claude/rules/agents/changemaker.md` | Changemaker role with event emission |
