# Changemaker Role

Activated when: deploying changes, updating configurations, restarting services
as part of planned work, or performing any infrastructure modification.

## Procedure

### 1. Pre-flight check

For EVERY target in your planned change:

```
ops_check_target(target=<target_name>)
```

If any target returns STOP — do not proceed. Inform the user.
If any target returns CAUTION — review the details and decide with the user.

### 2. Open change window

```
ops_create_change(
    targets=[<list of all targets>],
    description="<what you're doing and why>",
    created_by="claude-code",
    rollback_plan="<how to undo if it breaks>"
)
```

Save the change ID. This window tells NemoClaw "these restarts are planned."

### 3. Emit start event

```
ops_emit_event(
    source="claude-code",
    type="change.started",
    target=<primary_target>,
    related_change_id=<change_id>,
    data={"summary": "<what's being changed>"}
)
```

### 4. Execute the change

Perform the work. For each significant step, emit events:

- Container restart → `remediation.restart`
- Config update → `remediation.config_fix`
- Service deployment → use appropriate event type

### 5. Verify

After the change:
- Check that affected services are healthy
- `ops_check_target` should return GO for all targets
- Review logs for errors

### 6. Close change window

```
ops_close_change(
    change_id=<change_id>,
    status="completed",
    outcome="success"  # or "failed" or "rolled-back"
)
```

### 7. Emit completion event

```
ops_emit_event(
    source="claude-code",
    type="change.completed",  # or "change.failed"
    target=<primary_target>,
    related_change_id=<change_id>,
    data={"summary": "<outcome description>"}
)
```

## If Something Breaks

1. Don't just fix it silently — create an incident record
2. Emit `change.failed` event
3. Close the change window with `outcome="failed"`
4. Switch to Responder role for the incident
5. Document what went wrong in the incident record

## What NOT to do

- Don't deploy without opening a change window
- Don't restart services without pre-flight checks
- Don't forget to close your change window (it auto-expires in 4h, but don't rely on that)
- Don't leave a change window open as a "suppression shield"
