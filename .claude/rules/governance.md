# Corvus Governance Rules

These rules are mandatory for all Claude Code sessions working with
Corvus-managed infrastructure. They ensure operational coordination,
audit-grade traceability, and multi-agent awareness.

## 1. Pre-Action Conflict Check

Before ANY MODIFY+ action on an infrastructure target (container restart,
config change, deployment, service update), you MUST:

1. Call `ops_check_target(target=<target_name>)`
2. Read the recommendation:
   - **GO** — Proceed normally
   - **CAUTION** — Another agent has an active change window or low-severity
     incident. Review the details, proceed only if your work is compatible.
   - **STOP** — Active critical/high incident or conflicting change. Do NOT
     proceed. Inform the user and wait.

Never skip this check. Even if you "just restarted it a minute ago."

## 2. Event Emission

You MUST emit events for all state-changing actions using `ops_emit_event`.

| Action | Event Type | When |
|--------|-----------|------|
| Start planned work | `change.started` | After opening change window |
| Complete planned work | `change.completed` | After closing change window |
| Planned work failed | `change.failed` | When rollback is needed |
| Restart a container | `remediation.restart` | After restart completes |
| Fix a config | `remediation.config_fix` | After config applied |
| Start investigating | `incident.investigating` | When you begin looking |
| Resolve an incident | `incident.resolved` | After confirmed resolution |

If you performed an action and did not emit an event, you have a compliance gap.

## 3. Change Windows

For planned work (deployments, upgrades, config changes):

1. **Before starting**: `ops_create_change(targets=[...], description="...", created_by="claude-code")`
2. **During work**: Emit events for each step
3. **After completion**: `ops_close_change(change_id, status="completed", outcome="success")`

This prevents NemoClaw from alerting on your planned restarts.

## 4. Incident Records

When investigating infrastructure issues, create Corvus incident records —
not just markdown notes.

Use `ops_create_incident(target, title, severity, detected_by="claude-code")`.

Update the incident as you investigate:
- Set `investigation_summary` with your findings
- Set `root_cause` when identified
- Set `remediation_applied` when you fix it
- Resolve it when done

## 5. Session End Verification

Before ending any session that involved infrastructure work:

1. Call `ops_get_context` to review your session's events
2. Verify every MODIFY+ action has a corresponding event
3. Close any open change windows
4. Update any open incidents you were working on

If you find gaps, emit the missing events before ending the session.
