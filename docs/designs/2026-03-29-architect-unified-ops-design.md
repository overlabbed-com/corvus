# Unified Operational Protocol — Phase 1 Design

> Agent: Architect
> Workspace: automation
> Project: unified-ops-protocol
> Risk Level: APPROVE (modifies agent governance + Admin API + ops-agent + MCP tools)
> Generated: 2026-03-29

## Summary

Three deliverables that make agent-a and ops-agent operationally identical:
1. **Real-time event feed** -- agent-a sessions see ops-agent actions inline via polling MCP tool
2. **Agent-a ops compliance** -- agent-a emits events and creates incidents through the SOP
3. **Pre-action conflict check** -- both agents check SOP state before acting on targets

## Problem Statement

Agent-a and ops-agent share a database but not a protocol. Specific gaps:

| Gap | Impact |
|-----|--------|
| Agent-a restarts a container -> no incident record, no event | ops-agent doesn't know agent-a caused it |
| ops-agent rotates a credential -> agent-a's next session doesn't see it | agent-a may make decisions on stale state |
| ops-agent investigating a target -> agent-a starts working on same target | Stepping on each other |
| Agent-a deploys new stack -> change window closes -> ops-agent investigates restart | Race condition |
| ops-agent creates a problem record -> agent-a's Architect doesn't see it | Design decisions miss operational data |

## Proposed Solution

### Component 1: Real-Time Event Feed MCP Tool

New MCP tool: `ops_watch_events` — returns recent high-severity events since a cursor.

```python
@mcp.tool()
def ops_watch_events(
    since: str = "",
    min_severity: str = "warning",
    limit: int = 10,
) -> str:
    """Watch for recent operational events from ops-agent and other agents.

    Call periodically during agent sessions to stay aware of infrastructure
    changes happening in real-time. Returns events since the given timestamp
    (ISO8601), filtered to warning+ severity by default.

    First call: omit 'since' to get recent events.
    Subsequent calls: pass the latest event's timestamp as 'since'.
    """
```

**How agent-a uses it**: The governance rules add a periodic check -- every time agent-a is
about to modify infrastructure or at natural breakpoints, it calls `ops_watch_events`.
Not a background poll (agent-a doesn't have that), but a check-before-act pattern.

**Admin API endpoint**: Already exists — `GET /ops/events?since=...&severity=warning`.
The MCP tool just wraps it with sensible defaults and formatting.

### Component 2: Agent-A Ops Compliance Rules

Updates to agent governance rules:

**Rule 1: Agent-a MUST emit events for state-changing actions**

| Agent Action | Event Type | When |
|-----------|-----------|------|
| Responder restarts container | `remediation.restart` | After restart |
| Responder investigates issue | `incident.investigating` | On start |
| Changemaker merges PR | `change.completed` | After merge |
| Changemaker creates change window | `change.started` | Already exists |
| Sentinel detects anomaly | `incident.opened` | On detection |
| Any agent takes APPROVE action | `action.approved` | After operator approves |

Implementation: Add to governance rules Incident Workflow and Standard Workflow.
Agent-a uses the existing `ops_emit_event` MCP tool (already available).

**Rule 2: Agent-a Responder MUST create SOP incident records**

Currently, agent-a's Responder writes incident reports to `reports/` as markdown files.
New rule: agent-a Responder MUST ALSO create an incident via `ops_create_incident` MCP tool.
The file-based report is still written (for detail), but the SOP record is the
canonical tracking mechanism.

**Rule 3: Pre-action conflict check**

Before any MODIFY+ action on a target, agent-a MUST:
1. Call `ops_watch_events(since=<15min_ago>)` — any recent activity on this target?
2. Check active change windows — is someone else working on it?
3. Check open incidents — is there an active investigation?

If conflicts detected: STOP, report the conflict, ask the operator how to proceed.

New MCP tool to make this easy:

```python
@mcp.tool()
def ops_check_target(
    target: str,
) -> str:
    """Check a target's operational status before taking action.

    Returns: active change windows, open incidents, recent events,
    and a clear GO/CAUTION/STOP recommendation.

    MUST be called before any MODIFY+ action on an infrastructure target.
    """
```

This calls 3 endpoints in parallel:
- `GET /ops/changes/active` — filtered to target
- `GET /ops/incidents?target=...&status=open`
- `GET /ops/events?target=...&since=15min`

Returns a structured recommendation:
- **GO**: No conflicts. Proceed normally.
- **CAUTION**: Recent activity on this target. Review before proceeding.
- **STOP**: Active change window or open incident. Do not act without coordination.

### Component 3: Admin API Enhancement

New endpoint: `GET /ops/targets/{target}/status`

Consolidates target status into a single call:
```json
{
  "target": "vllm-primary",
  "change_windows": [],
  "open_incidents": [{"id": "INC-042", "status": "investigating", "detected_by": "ops-agent"}],
  "recent_events": [...],
  "cmdb": {"service_type": "inference", "host": "host-01", "critical": false},
  "recommendation": "CAUTION",
  "reason": "Active incident INC-042 being investigated by ops-agent"
}
```

## Implementation Plan

### Phase 1a: MCP Tools (new)
1. `ops_watch_events` — event feed with severity filter + cursor
2. `ops_check_target` — pre-action conflict check with GO/CAUTION/STOP

### Phase 1b: Admin API (new endpoint)
3. `GET /ops/targets/{target}/status` — consolidated target status

### Phase 1c: Agent Governance Updates
4. Update governance rules: event emission rules, incident record requirement, conflict check
5. Add operational protocol task procedure
6. Update Responder agent file: SOP incident creation requirement
7. Update Changemaker agent file: event emission requirement

### Phase 1d: Verification
8. E2E test: agent-a creates change window -> ops-agent suppresses -> agent-a closes -> ops-agent resumes
9. E2E test: ops-agent creates incident -> agent-a session sees it in event feed -> agent-a acknowledges
10. E2E test: agent-a Responder restarts container -> incident record created -> ops-agent sees it

## Risk Assessment

| Component | Blast Radius | Reversibility | Autonomy |
|-----------|-------------|---------------|----------|
| MCP tools (watch_events, check_target) | None | Trivial | AUTO |
| Admin API endpoint (target status) | Contained | Easy | AUTO |
| Governance.md updates | None (docs) | Trivial | AUTO |
| Task procedure (ops-protocol.md) | None (docs) | Trivial | AUTO |
| Agent file updates | None (docs) | Trivial | AUTO |

Overall: **AUTO for docs**, **APPROVE for MCP/API changes** (they modify the tool surface).

## Rollback Plan

1. MCP tools are additive — removing them doesn't break existing functionality
2. Admin API endpoint is new — no existing code depends on it
3. Governance rules are additive — no existing rules are modified, only extended
4. If the conflict check is too noisy, reduce sensitivity or make it advisory-only

## Dependency Map

- **Admin API** (`ops_events_routes.py`): new target status endpoint
- **MCP server** (`mcp_server.py`): 2 new tools
- **Agent governance** (governance rules): event emission + conflict check rules
- **Agent tasks** (ops-protocol): new operational procedure
- **Agent roles** (responder, changemaker): SOP integration requirements

## Responses to Advocate Findings

### F1: Rules-Only Enforcement — ACCEPTED
Add event emission verification to session end protocol in governance.md:
"MUST verify: all state-changing actions emitted events via ops_emit_event."
Also: `ops_check_target` logs a `session.target_check` event automatically,
creating an audit trail even when agent-a forgets to explicitly emit.

### F2: Polling Frequency — ACCEPTED
Define concrete checkpoints in ops-protocol.md:
1. Before any MODIFY+ action on a target (already specified)
2. After completing each Standard Workflow phase
3. When switching agent roles
4. Before presenting CHECKPOINT to operator
5. At session end (summary check)
These are existing natural pauses — no new overhead.

### F3: Age-Aware Recommendations — ACCEPTED
`ops_check_target` recommendation logic:
- Open incident < 2h old → STOP
- Open incident > 2h in "investigating" → CAUTION (may be stale)
- Open incident > 6h in "investigating" → GO with note (likely stale)
- Active change window → STOP (regardless of age — windows are short-lived)
- Events < 15 min → contributes to recommendation
- Events > 1h → does not contribute

### F4: Shared Event Taxonomy — ACCEPTED
Defined in `ops-protocol.md`:
```
change.started / change.completed / change.failed
incident.opened / incident.investigating / incident.resolved / incident.escalated
remediation.restart / remediation.config_fix / remediation.credential_rotation
session.started / session.ended
action.approved / action.denied / action.escalated
sweep.completed / sweep.anomaly
```
Both agents use this taxonomy. New types require documentation.

### F5: Tool Naming — ACCEPTED (no action)
Current naming is fine. Document convention in MCP server.

### F6: ops-agent Conflict Check -- DEFERRED to Phase 2
ops-agent's change window awareness handles the main case. Agent-a-activity-awareness in ops-agent
is Phase 2 scope.

## Lean Review

- **No new services**: Everything runs in existing Admin API + MCP server
- **No new databases**: Uses existing ops_events, ops_incidents, ops_changes tables
- **2 MCP tools, not 10**: `ops_watch_events` (feed) and `ops_check_target` (conflict) cover all cases
- **Governance rules, not code**: Agent compliance is enforced via rules files, not middleware
- **`ops_check_target` consolidates 3 calls**: Single tool instead of requiring agent to call 3 endpoints manually
- **Deferred**: SSE/WebSocket push (overkill for agent-a which runs synchronously), ops-agent conflict checking (ops-agent already has change window awareness from SOP)
