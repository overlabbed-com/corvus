# Change Window Protocol

Change windows prevent agent conflicts. Before an agent modifies a target,
it declares a change window. Other agents see CAUTION or STOP when they
check that target's status.

## Lifecycle

```
active → completed (success/partial/failed)
active → expired   (auto-expire after 4h)
```

## API

### Create Change Window
```
POST /ops/changes
```
```json
{
  "targets": ["vllm-primary", "vllm-default"],
  "description": "Deploying new vLLM model weights",
  "created_by": "claude-code",
  "rollback_plan": "Revert to previous model snapshot",
  "project": "corvus#42",
  "auto_expire": true
}
```

**Targets are immutable after creation.** This prevents retroactive
scope-widening of change windows (threat model T1.1).

### List Changes
```
GET /ops/changes?status=active&target=vllm-primary&created_by=claude-code
```

### Active Changes Only
```
GET /ops/changes/active
```

### Close Change Window
```
PATCH /ops/changes/{id}
```
```json
{
  "status": "completed",
  "outcome": "success"
}
```

## Auto-Expiry

Change windows with `auto_expire: true` (the default) expire after 4 hours.
A background task checks every 5 minutes and transitions expired windows to
`status: expired`, emitting a `change.expired` event.

This prevents stale change windows from suppressing alerts indefinitely.

## Target Status Integration

When an agent calls `GET /ops/events/targets/{target}/status`:

| Condition | Recommendation |
|-----------|---------------|
| No active changes or incidents | **GO** |
| Active change window | **CAUTION** |
| Active incident | **CAUTION** (medium/low) or **STOP** (high/critical) |
| Active change AND incident | **STOP** |

Agents MUST call target status before any MODIFY+ action.
