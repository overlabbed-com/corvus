# Responder Role

Activated when: infrastructure issue detected, alert received, incident reported,
or user asks you to investigate a problem.

## Procedure

### 1. Check before acting

```
ops_check_target(target=<affected_service>)
```

If another agent is already remediating (visible in active changes or recent
events), observe and wait. Don't duplicate work.

### 2. Create incident record

```
ops_create_incident(
    target=<service_name>,
    title="<clear description of the problem>",
    severity="<critical|high|medium|low>",
    detected_by="claude-code"
)
```

Save the incident ID — you'll update it throughout.

### 3. Emit investigating event

```
ops_emit_event(
    source="claude-code",
    type="incident.investigating",
    target=<service_name>,
    severity=<severity>,
    related_incident_id=<incident_id>
)
```

### 4. Investigate

- Read container logs
- Check recent events for context
- Look at CMDB for service type and dependencies
- Correlate with recent changes (was something just deployed?)
- Check metrics for patterns

### 5. Coordinate with ops-agent

Check `ops_watch_events` for ops-agent activity on the same target.

- If ops-agent is actively remediating — wait for its outcome
- If ops-agent escalated — it needs human help, that's why you're here
- If ops-agent is idle on this target — proceed with your investigation

### 6. Remediate

If you apply a fix:
- Emit the appropriate remediation event (`remediation.restart`, `remediation.config_fix`)
- Update the incident with `remediation_applied`

### 7. Resolve

When the issue is confirmed fixed:
- Update the incident: set `root_cause`, `investigation_summary`, status → resolved
- Emit `incident.resolved` event
- Verify the target is healthy: `ops_check_target` should return GO

## What NOT to do

- Don't investigate without creating an incident record
- Don't restart services without checking `ops_check_target` first
- Don't resolve an incident without documenting root cause
- Don't ignore ops-agent's active work on the same target
