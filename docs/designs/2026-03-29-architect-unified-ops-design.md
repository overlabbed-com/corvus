# Unified Operational Protocol — Phase 1 Design

> Agent: Architect
> Workspace: automation
> Project: 021-unified-ops-protocol
> Risk Level: APPROVE (modifies CC governance + Admin API + NemoClaw + MCP tools)
> Generated: 2026-03-29

## Summary

Three deliverables that make CC and NC operationally identical:
1. **Real-time event feed** — CC sessions see NC actions inline via polling MCP tool
2. **CC ops compliance** — CC emits events and creates incidents through the SOP
3. **Pre-action conflict check** — both agents check SOP state before acting on targets

## Problem Statement

CC and NC share a database but not a protocol. Specific gaps:

| Gap | Impact |
|-----|--------|
| CC restarts a container → no incident record, no event | NC doesn't know CC caused it |
| NC rotates a credential → CC's next session doesn't see it | CC may make decisions on stale state |
| NC investigating a target → CC starts working on same target | Stepping on each other |
| CC deploys new stack → change window closes → NC investigates restart | Race condition |
| NC creates a problem record → CC's Architect doesn't see it | Design decisions miss operational data |

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
    """Watch for recent operational events from NemoClaw and other agents.

    Call periodically during CC sessions to stay aware of infrastructure
    changes happening in real-time. Returns events since the given timestamp
    (ISO8601), filtered to warning+ severity by default.

    First call: omit 'since' to get recent events.
    Subsequent calls: pass the latest event's timestamp as 'since'.
    """
```

**How CC uses it**: The governance rules add a periodic check — every time CC is
about to modify infrastructure or at natural breakpoints, it calls `ops_watch_events`.
Not a background poll (CC doesn't have that), but a check-before-act pattern.

**Admin API endpoint**: Already exists — `GET /ops/events?since=...&severity=warning`.
The MCP tool just wraps it with sensible defaults and formatting.

### Component 2: CC Ops Compliance Rules

Updates to `.claude/rules/governance.md` and `.claude/rules/tasks/`:

**Rule 1: CC MUST emit events for state-changing actions**

| CC Action | Event Type | When |
|-----------|-----------|------|
| Responder restarts container | `remediation.restart` | After restart |
| Responder investigates issue | `incident.investigating` | On start |
| Changemaker merges PR | `change.completed` | After merge |
| Changemaker creates change window | `change.started` | Already exists |
| Sentinel detects anomaly | `incident.opened` | On detection |
| Any agent takes APPROVE action | `action.approved` | After Todd approves |

Implementation: Add to governance.md's Incident Workflow and Standard Workflow.
CC uses the existing `ops_emit_event` MCP tool (already available).

**Rule 2: CC Responder MUST create SOP incident records**

Currently, CC's Responder writes incident reports to `reports/` as markdown files.
New rule: CC Responder MUST ALSO create an incident via `ops_create_incident` MCP tool.
The file-based report is still written (for detail), but the SOP record is the
canonical tracking mechanism.

**Rule 3: Pre-action conflict check**

Before any MODIFY+ action on a target, CC MUST:
1. Call `ops_watch_events(since=<15min_ago>)` — any recent activity on this target?
2. Check active change windows — is someone else working on it?
3. Check open incidents — is there an active investigation?

If conflicts detected: STOP, report the conflict, ask Todd how to proceed.

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
  "open_incidents": [{"id": "INC-042", "status": "investigating", "detected_by": "nemoclaw"}],
  "recent_events": [...],
  "cmdb": {"service_type": "inference", "host": "tmtdockp01", "critical": false},
  "recommendation": "CAUTION",
  "reason": "Active incident INC-042 being investigated by NemoClaw"
}
```

## Implementation Plan

### Phase 1a: MCP Tools (new)
1. `ops_watch_events` — event feed with severity filter + cursor
2. `ops_check_target` — pre-action conflict check with GO/CAUTION/STOP

### Phase 1b: Admin API (new endpoint)
3. `GET /ops/targets/{target}/status` — consolidated target status

### Phase 1c: CC Governance Updates
4. Update governance.md: event emission rules, incident record requirement, conflict check
5. Add `.claude/rules/tasks/ops-protocol.md` — operational protocol task procedure
6. Update Responder agent file: SOP incident creation requirement
7. Update Changemaker agent file: event emission requirement

### Phase 1d: Verification
8. E2E test: CC creates change window → NC suppresses → CC closes → NC resumes
9. E2E test: NC creates incident → CC session sees it in event feed → CC acknowledges
10. E2E test: CC Responder restarts container → incident record created → NC sees it

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
- **CC governance** (`.claude/rules/governance.md`): event emission + conflict check rules
- **CC tasks** (`.claude/rules/tasks/ops-protocol.md`): new operational procedure
- **CC agents** (responder.md, changemaker.md): SOP integration requirements

## Responses to Advocate Findings

### F1: Rules-Only Enforcement — ACCEPTED
Add event emission verification to session end protocol in governance.md:
"MUST verify: all state-changing actions emitted events via ops_emit_event."
Also: `ops_check_target` logs a `session.target_check` event automatically,
creating an audit trail even when CC forgets to explicitly emit.

### F2: Polling Frequency — ACCEPTED
Define concrete checkpoints in ops-protocol.md:
1. Before any MODIFY+ action on a target (already specified)
2. After completing each Standard Workflow phase
3. When switching agent roles
4. Before presenting CHECKPOINT to Todd
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

### F6: NC Conflict Check — DEFERRED to Phase 2
NC's change window awareness handles the main case. CC-activity-awareness in NC
is Phase 2 scope.

## Lean Review

- **No new services**: Everything runs in existing Admin API + MCP server
- **No new databases**: Uses existing ops_events, ops_incidents, ops_changes tables
- **2 MCP tools, not 10**: `ops_watch_events` (feed) and `ops_check_target` (conflict) cover all cases
- **Governance rules, not code**: CC compliance is enforced via rules files, not middleware
- **`ops_check_target` consolidates 3 calls**: Single tool instead of requiring CC to call 3 endpoints manually
- **Deferred**: SSE/WebSocket push (overkill for CC which runs synchronously), NemoClaw conflict checking (NC already has change window awareness from Project 019)
