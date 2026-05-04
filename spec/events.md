# Event Protocol

Events are the atomic unit of operational awareness in Corvus. Every state-changing
action by any agent produces an event. Events are OCSF 1.3.0-transformed and
forwarded to your SIEM.

## Event Types

### Change Lifecycle
| Type | When | Severity |
|------|------|----------|
| `change.started` | Agent declares a change window | info |
| `change.completed` | Change finished successfully | info |
| `change.failed` | Change failed | warning |
| `change.expired` | Change window auto-expired | info |

### Incident Lifecycle
| Type | When | Severity |
|------|------|----------|
| `incident.opened` | New incident detected | warning-critical |
| `incident.investigating` | Investigation in progress | info |
| `incident.resolved` | Incident resolved | info |
| `incident.escalated` | Escalated to human | warning |

### Remediation
| Type | When | Severity |
|------|------|----------|
| `remediation.restart` | Container/service restarted | warning |
| `remediation.config_fix` | Configuration change applied | info |
| `remediation.credential_rotation` | Credentials rotated | warning |

### Sweep / Scan
| Type | When | Severity |
|------|------|----------|
| `sweep.completed` | Health sweep finished | info |
| `sweep.anomaly` | Anomaly detected during sweep | warning |
| `anomaly.detected` | Anomaly detected outside a sweep context (continuous monitor) | warning |

### LLM Investigation
Read-only forensics driven by an LLM (not an action or a plan). Parallels session lifecycle.

| Type | When | Severity |
|------|------|----------|
| `llm.investigation_started` | LLM investigation of a target began | info |
| `llm.investigation_completed` | LLM investigation finished with findings | info |

### Actions
| Type | When | Severity |
|------|------|----------|
| `action.approved` | Action approved (trust ledger) | info |
| `action.denied` | Action denied | warning |

### Sessions
| Type | When | Severity |
|------|------|----------|
| `session.started` | Agent session begins | info |
| `session.ended` | Agent session ends | info |

### Auth (OIDC migration observability)
| Type | When | Severity |
|------|------|----------|
| `auth.oidc_validation_failed` | A bearer JWT failed validation (signature, audience, expiry, scope) | warning |
| `auth.break_glass_used` | The `corvus-break-glass` static key was used as Bearer (P1) | critical |
| `sentinel.synthetic_probe.ok` | Periodic out-of-band liveness probe minted a JWT and exercised an authenticated endpoint successfully | info |
| `sentinel.synthetic_probe.failed` | The synthetic probe failed at any step (mint, endpoint, emit) — auth path is degraded | warning |

### Plan Lifecycle
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

### Lean Metrics
| Type | When | Severity |
|------|------|----------|
| `metrics.snapshot` | Metrics collection cycle completed | info |
| `metrics.anomaly` | Metric crossed threshold | warning |
| `metrics.adjustment` | Auto-tune applied a correction | warning |
| `metrics.revert` | Auto-tune reverted a correction | warning |
| `metrics.converged` | Parameter dampening factor < 0.05 | info |

### Correlation
| Type | When | Severity |
|------|------|----------|
| `correlation.group_created` | 2+ incidents share a resource (GPU, network, volume, dependency) | warning |
| `correlation.group_resolved` | All incidents in a correlation group resolved | info |

#### Correlation Group Event Schema

```json
{
  "source": "corvus-server",
  "type": "correlation.group_created",
  "target": "gpu:host-03:0",
  "severity": "warning",
  "data": {
    "group_id": "CG-A1B2C3D4",
    "root_cause": "Check GPU state (VRAM, temperature, driver)",
    "shared_resource": "gpu:host-03:0",
    "shared_resource_type": "gpu",
    "member_incidents": ["INC-001", "INC-002", "INC-003"]
  }
}
```

### Gaps (Blind Spot Detection)
| Type | When | Severity |
|------|------|----------|
| `gap:accuracy:*` | Triage couldn't diagnose | warning |
| `gap:coverage:*` | No runbook or classification | warning |
| `gap:coverage:config-drift:*` | Running config diverges from declared state | warning |
| `gap:autonomy:*` | Manual intervention required | info |
| `gap:efficiency:*` | Slow resolution detected | info |

## API

### Emit Event
```
POST /ops/events
```
```json
{
  "source": "agent-a",
  "type": "change.completed",
  "target": "admin-api",
  "severity": "info",
  "data": {"summary": "Deployed OCSF transformer v2"},
  "related_change_id": "CHG-A1B2C3D4"
}
```

### List Events
```
GET /ops/events?since=2026-03-29T00:00:00Z&severity=warning&target=vllm-primary&limit=50
```

### Session Briefing
```
GET /ops/events/context
```
Returns last 24h events sorted by severity. Call at session start.

### Target Status
```
GET /ops/events/targets/{target}/status
```
Returns GO/CAUTION/STOP recommendation with active changes, incidents, and recent events.

## OCSF Mapping

Every event is transformed to OCSF 1.3.0 before SIEM forwarding:

| SOP Type | OCSF Class | Class UID |
|----------|-----------|-----------|
| `incident.*` | Incident Finding | 2005 |
| `change.*` | Device Config State Change | 5019 |
| `plan.*` | Device Config State Change | 5019 |
| `remediation.*` | Remediation Activity | 7001 |
| `sweep.*` | Scan Activity / Detection Finding | 6007/2004 |
| `anomaly.detected` | Detection Finding | 2004 |
| `llm.*` | Application Lifecycle | 6002 |
| `action.*` | API Activity | 6003 |
| `session.*` | Application Lifecycle | 6002 |
| `gap:*` | Compliance Finding | 2003 |
| `metrics.*` | Compliance Finding | 2003 |

Graph edge metadata (parent/child, caused_by, triggered) is stored in the
`unmapped` field for traversal in your SIEM.

## Correlation Groups

When 2+ incidents share a resource (GPU, network, volume, dependency), Corvus
creates a correlation group. Agents send a single alert for the group, not
per-member alerts.

#### Correlation Rules

| Rule | Trigger | Root Cause Hint |
|------|---------|-----------------|
| `shared_gpu_failure` | 2+ incidents on same host+gpu_index within same sweep | Check GPU state (VRAM, temperature, driver) |
| `shared_dependency_failure` | 2+ incidents where targets share a DEPENDS_ON edge to a common unhealthy service | Fix the dependency first |
| `shared_host_failure` | 5+ incidents on same host within same sweep | Host resource exhaustion (disk, RAM, network) |
| `shared_volume_failure` | 2+ incidents on services sharing a MOUNTS edge to the same volume | Storage failure (NFS timeout, disk full) |

#### Correlation Group Data Schema

```json
{
  "group_id": "CG-A1B2C3D4",
  "root_cause": "CUDA OOM on GPU 0",
  "shared_resource": "gpu:host-03:0",
  "shared_resource_type": "gpu",
  "member_incidents": ["INC-001", "INC-002", "INC-003", "INC-004"],
  "created_at": "2026-03-30T08:09:00Z"
}
```

#### API Endpoints

**Check for Correlation**
```
POST /ops/correlations/check
```
Request:
```json
{
  "incidents": ["INC-001", "INC-002", "INC-003"],
  "host": "host-03",
  "sweep_id": "SWEEP-001"
}
```

Response (correlated):
```json
{
  "correlated": true,
  "group": {
    "group_id": "CG-A1B2C3D4",
    "root_cause": "Check GPU state (VRAM, temperature, driver) on gpu:host-03:0",
    "shared_resource": "gpu:host-03:0",
    "shared_resource_type": "gpu",
    "member_incidents": ["INC-001", "INC-002"],
    "created_at": "2026-03-30T08:09:00Z"
  },
  "message": "Found shared GPU: gpu:host-03:0"
}
```

Response (not correlated):
```json
{
  "correlated": false,
  "group": null,
  "message": "No shared resources detected — incidents are independent"
}
```

**Get Correlation Group**
```
GET /ops/correlations/group/{group_id}
```

**List Active Correlations**
```
GET /ops/correlations/active
```

#### Agent Contract

- When creating multiple incidents in the same sweep, agents MUST call
  `POST /ops/correlations/check` to detect group eligibility
- Agents MUST send a single Slack alert for a correlation group, not per-member
- Individual incidents are still created (for tracking) but are NOT separately alerted
- The group alert MUST include the shared resource and root cause hint
- Corvus server auto-runs correlation sweep every 5 minutes to detect missed correlations
