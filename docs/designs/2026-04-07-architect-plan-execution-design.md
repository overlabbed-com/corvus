# Plan Execution Subsystem Design

> **Author**: Claude Code (Architect)
> **Date**: 2026-04-07
> **Status**: Design approved, pending Advocate challenge
> **Corvus Component**: New subsystem — `plans` router, models, MCP tools

## Problem Statement

Corvus coordinates multi-agent operations through events, change windows, and
triage runbooks. But there is no concept of a **plan** — a structured, multi-step
work order that one agent creates and another executes. Today, CC interactively
designs and implements changes in a single session. This means:

1. the operator must be present for the entire cycle (plan + execute + verify)
2. Fleet-wide operations (same action across N hosts) execute serially
3. Complex DAG-ordered deployments have no formal structure — they're ad-hoc
4. NemoClaw has no way to receive structured work from CC

The plan execution subsystem makes plans a first-class Corvus primitive, enabling
CC to produce plans during interactive time and NemoClaw to execute them
asynchronously and in parallel.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Execution pattern | Both fleet (parallel) and DAG (ordered) | Fleet ops are embarrassingly parallel; deployments need ordering. Same system handles both via dependency edges |
| Authorship | Any agent creates, trust ledger gates execution | Plans are agent-agnostic. Each step's action_type is checked against trust tiers independently |
| Change window integration | Plan owns the window, steps inherit it | Extends existing change protocol. Steps outside declared targets are rejected |
| Failure handling | Per-step policy (halt/skip/retry) + per-step rollback | halt is default. Steps that don't declare a policy default to halt. Every mutation step requires a rollback block |
| Rollback | Per-step (not plan-level) | Enables unwinding to any point. On halt-failure, completed steps roll back in reverse order using their individual rollback blocks |
| Implementation approach | New subsystem alongside triage steps | Triage steps are investigation-oriented; plans are mutation-oriented. Clean separation prevents cross-contamination |

## Data Model

### Plan Lifecycle

```
draft → approved → executing → completed | failed | blocked | rolling_back
```

- **draft**: Created by an agent, not yet approved
- **approved**: Human or trust ledger has approved all steps
- **executing**: Change window open, steps being dispatched
- **completed**: All steps succeeded
- **failed**: A halt-policy step failed, rollback completed
- **blocked**: A halt-policy step failed, awaiting human decision
- **rolling_back**: Executing rollback steps in reverse order

### ops_plans Table

```sql
CREATE TABLE IF NOT EXISTS ops_plans (
    id              TEXT PRIMARY KEY,       -- PLN-XXXXXXXX
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL,          -- agent identity
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',
    targets         TEXT NOT NULL,          -- JSON array: all targets across all steps
    change_id       TEXT,                   -- FK to ops_changes (created on execute)
    approval_method TEXT,                   -- human / trust_ledger
    approved_at     TEXT,
    approved_by     TEXT,
    completed_at    TEXT,
    outcome         TEXT,                   -- success / partial / failed / rolled_back
    rollback_to     TEXT,                   -- step ID: how far rollback has unwound
    node_id         TEXT DEFAULT 'local',
    hlc_timestamp   TEXT
);

CREATE INDEX IF NOT EXISTS idx_plans_status ON ops_plans(status);
CREATE INDEX IF NOT EXISTS idx_plans_created_by ON ops_plans(created_by);
CREATE INDEX IF NOT EXISTS idx_plans_change_id ON ops_plans(change_id);
```

### ops_plan_steps Table

```sql
CREATE TABLE IF NOT EXISTS ops_plan_steps (
    id              TEXT PRIMARY KEY,       -- PSTEP-XXXXXXXX
    plan_id         TEXT NOT NULL,          -- FK to ops_plans
    name            TEXT NOT NULL,
    description     TEXT,
    sequence        INTEGER NOT NULL,       -- execution order within dependency group
    depends_on      TEXT NOT NULL DEFAULT '[]',  -- JSON array of step IDs (DAG edges)
    action_type     TEXT NOT NULL,          -- trust ledger key
    targets         TEXT NOT NULL,          -- JSON array: specific targets for this step
    params          TEXT NOT NULL DEFAULT '{}',   -- JSON: action parameters
    failure_policy  TEXT NOT NULL DEFAULT 'halt', -- halt / skip / retry
    max_retries     INTEGER NOT NULL DEFAULT 0,
    rollback        TEXT,                   -- JSON: rollback action definition (required for mutations)
    timeout         INTEGER NOT NULL DEFAULT 300,  -- seconds
    status          TEXT NOT NULL DEFAULT 'pending',
    output          TEXT,                   -- JSON: execution result
    error           TEXT,
    executed_by     TEXT,                   -- agent that ran it
    started_at      TEXT,
    completed_at    TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (plan_id) REFERENCES ops_plans(id)
);

CREATE INDEX IF NOT EXISTS idx_plan_steps_plan ON ops_plan_steps(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_steps_status ON ops_plan_steps(status);
CREATE INDEX IF NOT EXISTS idx_plan_steps_action_type ON ops_plan_steps(action_type);
```

### DAG Execution Rules

1. A step is `ready` when all steps in its `depends_on` list are `completed`
2. All `ready` steps can execute in parallel (fleet fan-out)
3. Steps with empty `depends_on` are ready immediately (DAG roots)
4. When a `halt`-policy step fails, no new steps become `ready`
5. `skip`-policy failures: step marked `failed`, dependents still become ready
6. `retry`-policy failures: re-queue up to `max_retries`, then follow halt behavior

### Target Scope Enforcement

Steps that reference targets not in the plan's `targets` array are rejected at
creation time. This prevents scope creep after approval — the plan's target list
is the contract.

The `@host` convention (e.g., `tetragon@host-01`) enables fleet fan-out:
one logical step can expand to N parallel host-scoped executions while keeping
all targets in the declared scope.

## API

### Plan Management

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/ops/plans` | Create a plan (draft) |
| `GET` | `/ops/plans` | List plans (filter: status, created_by) |
| `GET` | `/ops/plans/{id}` | Get plan with all steps |
| `POST` | `/ops/plans/{id}/approve` | Approve plan for execution |
| `POST` | `/ops/plans/{id}/execute` | Start execution (creates change window) |
| `POST` | `/ops/plans/{id}/cancel` | Cancel draft or halt executing plan |
| `POST` | `/ops/plans/{id}/rollback` | Trigger rollback from current point |

### Step Execution

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ops/plans/{id}/steps/ready` | Pull next executable steps |
| `POST` | `/ops/plans/{id}/steps/{step_id}/result` | Report step completion |
| `GET` | `/ops/plans/{id}/status` | Execution summary (progress, blockers) |

### Approval Flow

`POST /ops/plans/{id}/approve` checks every step's `action_type` against the
trust ledger:

- **All steps AUTO**: Auto-approves. `approval_method = "trust_ledger"`
- **Any step ESCALATE or above**: Returns `needs_approval: true` with the list
  of steps that exceed the executing agent's trust tier
- **Mixed**: Response shows which steps are pre-approved and which need human sign-off

### Execute Flow

`POST /ops/plans/{id}/execute`:
1. Validates plan is `approved`
2. Creates change window via existing `ops_changes` covering all plan targets
3. Sets plan status to `executing`
4. Marks root steps (no dependencies) as `ready`
5. Emits `plan.started` event with change_id

### Rollback Mechanics

When a `halt`-policy step fails:
1. Plan status transitions to `rolling_back`
2. Server builds rollback sequence: all `completed` steps in reverse `sequence` order
3. Each completed step's `rollback` block becomes a new executable action
4. Agent polls ready rollback steps using the same step protocol
5. On rollback completion: plan status → `failed`, change window closed with
   `outcome: "rolled_back"`

Steps with `skip` failure policy are marked `failed` but their rollback is not
triggered unless the entire plan rolls back.

## Trust Ledger Integration

The plan subsystem does not introduce a new authorization model. It delegates
to the existing trust ledger:

```
Plan submitted → for each step:
  trust_tier = ops_trust_ledger[step.action_type]
  if trust_tier == AUTO: pre-approved
  if trust_tier == NOTIFY: pre-approved, notify on execution
  if trust_tier == ESCALATE: requires human approval
  if trust_tier == BLOCKED: step rejected, plan cannot be approved
```

This means NemoClaw's graduated autonomy (spiral slices) naturally gates what
plans it can self-execute:

| Slice | Can Self-Approve | Needs the operator |
|-------|-----------------|------------|
| 1-2 (eyes+hands) | health.check, remediation.restart | change.deploy, change.config |
| 3 (muscle) | + change.deploy (after trust earned) | change.config on critical services |
| 4+ (brain) | Most action types | Novel/unprecedented actions |

## Event Types

New event types for the plan lifecycle:

| Type | When | Severity |
|------|------|----------|
| `plan.created` | Plan submitted as draft | info |
| `plan.approved` | Plan approved for execution | info |
| `plan.started` | Execution began, change window opened | info |
| `plan.step_completed` | Individual step succeeded | info |
| `plan.step_failed` | Individual step failed | warning |
| `plan.completed` | All steps succeeded | info |
| `plan.failed` | Step failure, rollback completed | warning |
| `plan.blocked` | Step failure, awaiting human decision | warning |
| `plan.rolling_back` | Rollback sequence started | warning |
| `plan.rolled_back` | Rollback sequence completed | info |

OCSF mapping: Device Config State Change (5019), consistent with change events.

## MCP Tools

### For Plan Creators (CC)

```python
ops_create_plan(title, description, steps) -> plan_id
ops_approve_plan(plan_id) -> approval_result
ops_execute_plan(plan_id) -> change_id + initial ready steps
ops_plan_status(plan_id) -> execution summary
ops_cancel_plan(plan_id) -> cancellation result
ops_rollback_plan(plan_id) -> rollback initiation result
```

### For Plan Executors (NemoClaw)

```python
ops_pull_ready_steps(plan_id) -> list of ready steps
ops_report_step_result(plan_id, step_id, success, output, error) -> next ready steps + plan status
```

## CC Integration Pattern

The plan subsystem integrates into the existing CC governance workflow:

```
1. CC (Architect) designs the change
2. CC (Advocate) challenges the design
3. the operator approves the design (existing CHECKPOINT)
4. CC (Changemaker) calls ops_create_plan() with structured steps
5. CC calls ops_approve_plan() — trust ledger gates
   - All AUTO: proceeds
   - Any ESCALATE: presents to the operator with blast radius per step
6. the operator approves → CC calls ops_execute_plan()
7. NemoClaw polls ops_pull_ready_steps(), executes, reports results
8. CC or the operator monitors via ops_plan_status()
9. On completion: change window auto-closes, plan.completed event emitted
```

### Plan Granularity by Trust Tier

CC adjusts plan granularity based on NemoClaw's current capabilities:

**Slice 1-2**: Granular step-by-step (restart X, check health, report)
**Slice 3-4**: Objective-level (deploy policy set to fleet, verify all hosts)
**Slice 5+**: Intent-level (improve tetragon coverage), NemoClaw self-decomposes

## Risk Assessment

| Risk | Blast Radius | Reversibility | Mitigation |
|------|-------------|---------------|------------|
| Plan targets wrong services | Multi-service | Moderate (rollback) | Target validation against CMDB, human approval for non-AUTO steps |
| Rollback step fails | Contained | Difficult | Plan enters `blocked`, escalates to the operator. Rollback failures never auto-retry |
| Stale plan executed after environment changed | Multi-service | Moderate | Plans auto-expire after 24h in `approved` state. CMDB drift check on execute |
| Agent claims step but crashes mid-execution | Contained | Easy (re-queue) | Step timeout → re-queued as `pending`. Max 1 retry from timeout |
| Trust ledger bypassed | Infrastructure | Difficult | Approval check is server-side, not agent-side. No client can skip it |

## Rollback Plan

The plan subsystem is additive — new tables, new router, new MCP tools. Removal
requires dropping `ops_plans` and `ops_plan_steps` tables, removing the router
registration, and removing MCP tool functions. No existing functionality is modified.

## Dependencies

- `ops_changes` (change window creation)
- `ops_trust_ledger` (step approval)
- `ops_events` (lifecycle events)
- `ops_cmdb` (target validation)
- Existing MCP server (`mcp_server.py`)
