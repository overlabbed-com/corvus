# Plan Execution Protocol

Plans are structured work orders with DAG-ordered steps, trust-ledger gating,
and per-step rollback. They replace ad-hoc multi-step operations with an
auditable, resumable execution model.

A plan declares what to do, in what order, and what to undo if it fails.
The server owns scheduling; agents pull ready steps and report results.

## Lifecycle

```
draft → approved → executing → completed | failed | blocked | rolling_back
                                                               └→ failed (outcome: rolled_back)
```

| Transition | Trigger |
|-----------|---------|
| draft → approved | `POST /approve` — trust ledger auto-approves or human override |
| approved → executing | `POST /execute` — opens change window, marks root steps ready |
| executing → completed | All steps succeeded (outcome: success) or some skipped (outcome: partial) |
| executing → blocked | Step failed with `halt` policy |
| blocked → cancelled | `POST /cancel` |
| blocked → rolling_back | `POST /rollback` |
| rolling_back → failed | All rollback steps finished (outcome: rolled_back) |
| draft/approved/blocked → cancelled | `POST /cancel` |

## API

### Create Plan
```
POST /ops/plans
```
```json
{
  "title": "Deploy Tetragon policies fleet-wide",
  "description": "Roll out 27 TracingPolicy CRDs to all 4 Docker hosts",
  "created_by": "claude-code",
  "expires_hours": 24,
  "steps": [
    {
      "name": "deploy-host-01",
      "sequence": 1,
      "depends_on": [],
      "action_type": "remediation.config_fix",
      "targets": ["tetragon@tmthost-01"],
      "params": {"compose_path": "stacks/security/tetragon"},
      "failure_policy": "halt",
      "max_retries": 0,
      "rollback": {"action_type": "remediation.config_fix", "params": {"revert": true}},
      "timeout": 300
    },
    {
      "name": "verify-host-01",
      "sequence": 2,
      "depends_on": ["deploy-host-01"],
      "action_type": "sweep.health_check",
      "targets": ["tetragon@tmthost-01"],
      "params": {"expect_policies": 27},
      "failure_policy": "halt",
      "max_retries": 1,
      "timeout": 60
    }
  ]
}
```

Returns `201` with the full plan including generated IDs. Plan targets are
auto-computed as the union of all step targets.

### List Plans
```
GET /ops/plans?status=executing&created_by=claude-code
```

### Get Plan
```
GET /ops/plans/{id}
```
Returns plan with all steps included.

### Approve Plan
```
POST /ops/plans/{id}/approve
```
```json
{
  "approved_by": "operator",
  "force": false
}
```

If all step action_types (plus `plan.execute`) are AUTO or SUPERVISED in the
trust ledger, the plan is auto-approved (`approval_method: "trust_ledger"`).

If any are ESCALATE, returns:
```json
{
  "needs_approval": true,
  "plan_id": "PLN-A1B2C3D4",
  "escalated_steps": [
    {"step_id": "PSTEP-E5F6G7H8", "step_name": "deploy-host-01", "action_type": "remediation.config_fix", "trust_tier": "ESCALATE"}
  ]
}
```

Retry with `force: true` to human-override (`approval_method: "human"`).

### Execute Plan
```
POST /ops/plans/{id}/execute
```
Only approved plans. Creates a change window covering all plan targets,
marks root steps (empty `depends_on`) as ready, emits `plan.started`.

### Cancel Plan
```
POST /ops/plans/{id}/cancel
```
Only draft, approved, or blocked plans.

### Rollback Plan
```
POST /ops/plans/{id}/rollback
```
Only completed or blocked plans. Creates reverse-order rollback steps from
completed steps that have rollback definitions. Sets plan status to
`rolling_back`. See Rollback Mechanics below.

### Get Ready Steps
```
GET /ops/plans/{id}/steps/ready
```
Returns ready steps and atomically claims them (marks as `executing` with
`started_at`). This is the agent pull endpoint.

### Report Step Result
```
POST /ops/plans/{id}/steps/{step_id}/result
```
```json
{
  "success": true,
  "output": {"policies_loaded": 27},
  "error": null
}
```

Returns current plan status and any newly-ready steps:
```json
{
  "step_id": "PSTEP-E5F6G7H8",
  "step_status": "completed",
  "plan_status": "executing",
  "retry_count": 0,
  "next_ready_steps": [
    {"id": "PSTEP-I9J0K1L2", "name": "verify-host-01", "action_type": "sweep.health_check"}
  ]
}
```

### Get Plan Status
```
GET /ops/plans/{id}/status
```
```json
{
  "id": "PLN-A1B2C3D4",
  "status": "executing",
  "title": "Deploy Tetragon policies fleet-wide",
  "change_id": "CHG-M3N4O5P6",
  "total_steps": 8,
  "pending": 4,
  "ready": 2,
  "executing": 1,
  "completed": 1,
  "failed": 0,
  "skipped": 0,
  "rolled_back": 0,
  "progress_pct": 12.5
}
```

## Step Schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Unique within plan; used in `depends_on` references |
| `description` | string | null | Human-readable purpose |
| `sequence` | int | required | Display ordering; DAG edges override for execution |
| `depends_on` | list[string] | `[]` | Step names this step waits for (resolved to IDs at creation) |
| `action_type` | string | required | Trust ledger key (e.g., `remediation.restart`, `sweep.health_check`) |
| `targets` | list[string] | required | Service targets, supports `@host` convention |
| `params` | dict | `{}` | Action-specific parameters passed to the executing agent |
| `failure_policy` | string | `"halt"` | One of: `halt`, `skip`, `retry` |
| `max_retries` | int | `0` | Only meaningful when `failure_policy` is `retry` |
| `rollback` | dict or null | `null` | Rollback definition: `{action_type, params}` |
| `timeout` | int | `300` | Seconds before the agent should consider the step timed out |

## DAG Execution Rules

Steps form a directed acyclic graph via `depends_on`. Execution follows these
rules:

1. A step is **ready** when all steps in its `depends_on` list are `completed`
   or `skipped`.
2. All ready steps execute **in parallel** (agents claim them via
   `GET /steps/ready`).
3. Steps with an empty `depends_on` are DAG roots — they become ready
   immediately when the plan starts executing.
4. The server re-evaluates the DAG after every step result report.

## Failure Policy Semantics

| Policy | Behavior on failure |
|--------|-------------------|
| `halt` | Step marked `failed`. Plan transitions to `blocked`. No further steps are scheduled. Human decides: cancel, rollback, or fix and retry. |
| `skip` | Step marked `skipped`. Treated as done for dependency resolution. Downstream steps proceed. Plan completes with outcome `partial`. |
| `retry` | Step re-queued as `ready` with `retry_count` incremented. If `retry_count > max_retries`, falls back to `halt` behavior. |

## Rollback Mechanics

Rollback is triggered via `POST /plans/{id}/rollback` on completed or blocked
plans.

1. Server finds all `completed` steps that have a non-null `rollback` definition.
2. Rollback steps are created in **reverse sequence order** — last completed step
   rolls back first.
3. Each rollback step depends on the previous rollback step (serial chain).
4. Rollback steps are regular plan steps: they follow the same claim/result
   protocol and appear in the step list with `rollback:` name prefix.
5. The first rollback step is immediately `ready`; subsequent ones are `pending`.
6. When all rollback steps complete, the plan transitions to `failed` with
   outcome `rolled_back`.
7. Rollback steps themselves use `halt` failure policy with no retries. A failed
   rollback step blocks the rollback sequence and requires human intervention.

## Trust Ledger Integration

Plan approval queries the trust ledger for each unique `action_type` across all
steps, plus the synthetic `plan.execute` action:

- **AUTO / SUPERVISED**: Plan auto-approved (`approval_method: "trust_ledger"`).
- **ESCALATE**: Returns `needs_approval` with the list of escalated steps.
  Human must call approve with `force: true` (`approval_method: "human"`).

The trust ledger tracks success/failure rates per action_type. Agents earn
trust through demonstrated competence (ESCALATE -> SUPERVISED -> AUTO).
Plan execution outcomes feed back into the ledger.

## Change Window Integration

When a plan starts executing, the server creates a change window covering
all plan targets (union of all step targets). This ensures:

- Other agents see CAUTION/STOP when checking targets under active plans.
- The change window auto-expires based on `expires_hours`.
- Plan completion (success, partial, or rolled_back) closes the change window.
- Steps targeting services outside the plan's target set are rejected at
  creation time (targets are immutable after plan creation).

## @host Fan-Out Convention

Multi-host operations use the `service@host` naming convention:

```
tetragon@tmthost-01
tetragon@tmthost-02
tetragon@tmthost-03
tetragon@tmthost-04
```

The creating agent (CC) expands `@host` targets at plan creation time.
Each host gets its own step, enabling per-host failure isolation and
parallel execution within the same sequence group.

## Plan Expiry

- `expires_hours` is set at creation (default: 24, max: 72).
- Approved plans that are not executed before expiry are subject to the
  change window auto-expire mechanism.
- Executing plans whose change window expires will have the window closed
  by the background expiry task, emitting a `change.expired` event.

## Agent Contract

Agents executing plan steps MUST:

1. **Poll ready steps** via `GET /plans/{id}/steps/ready` at regular intervals
   or after receiving `next_ready_steps` in a result response.
2. **Claim before executing** — the `GET /steps/ready` endpoint atomically
   marks steps as `executing`. Do not execute unclaimed steps.
3. **Report results** via `POST /plans/{id}/steps/{step_id}/result` with
   `success`, `output`, and `error` fields.
4. **Respect timeouts** — if a step exceeds its `timeout`, report failure
   with an appropriate error message.
5. **Do not skip steps** — only the server applies failure policies.
6. **Emit events** for significant actions taken during step execution
   (restarts, config changes) via the normal event protocol.
