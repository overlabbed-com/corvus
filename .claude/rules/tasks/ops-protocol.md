# Operational Protocol Task

This procedure applies to every CC session that interacts with infrastructure.
Load it at session start. Follow it throughout.

## Session Start

1. Call `ops_get_context` for situational awareness
2. Review:
   - Active change windows (who is doing what)
   - Open incidents (what is broken)
   - Recent events (what just happened)
3. If there are active incidents on targets you plan to touch — coordinate,
   don't collide

## Event Type Taxonomy

### Change lifecycle
- `change.started` — Planned work begins
- `change.completed` — Planned work finished successfully
- `change.failed` — Planned work failed, rollback needed

### Incident lifecycle
- `incident.opened` — New issue detected
- `incident.investigating` — Active investigation
- `incident.resolved` — Issue confirmed fixed
- `incident.escalated` — Needs human intervention

### Remediation actions
- `remediation.restart` — Container/service restarted
- `remediation.config_fix` — Configuration corrected
- `remediation.credential_rotation` — Credentials rotated

### Monitoring
- `sweep.completed` — Health sweep cycle finished
- `sweep.anomaly` — Anomaly detected during sweep

### Session
- `session.started` — CC session begins
- `session.ended` — CC session ends

## Checkpoints

Check for new events from other agents at these moments:

- **Role switches** — When switching between responder/changemaker roles
- **Before MODIFY actions** — Always call `ops_check_target` first
- **After long-running tasks** — If 10+ minutes passed, check `ops_watch_events`
- **Before session end** — Final review of all activity

## Creating Incidents

Create an incident when you observe:
- Unexpected service failure or unhealthy state
- Performance degradation beyond baseline
- Security concern (unauthorized access, exposed secrets)
- Data integrity issue

Required fields:
- `target` — The affected service name (must match CMDB)
- `title` — Clear, specific description
- `severity` — critical / high / medium / low
- `detected_by` — "claude-code"

Link to change windows when the incident may be related to recent work.

## Session End Checklist

Before ending:

- [ ] All MODIFY+ actions emitted corresponding events
- [ ] All open change windows closed with outcome
- [ ] All incidents you opened are updated (resolved or handed off)
- [ ] Call `ops_get_context` to confirm nothing was missed
