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

### Correlation
| Type | When | Severity |
|------|------|----------|
| `correlation.group_created` | 2+ incidents share a resource (GPU, network, volume, dependency) | warning |
| `correlation.group_resolved` | All incidents in a correlation group resolved | info |

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
| `remediation.*` | Remediation Activity | 7001 |
| `sweep.*` | Scan Activity / Detection Finding | 6007/2004 |
| `action.*` | API Activity | 6003 |
| `session.*` | Application Lifecycle | 6002 |
| `gap:*` | Compliance Finding | 2003 |

Graph edge metadata (parent/child, caused_by, triggered) is stored in the
`unmapped` field for traversal in your SIEM.

## Correlation Groups

When 2+ incidents share a resource (GPU, network, volume, dependency), Corvus
creates a correlation group. Agents send a single alert for the group, not
per-member alerts.

### Correlation Rules

| Rule | Trigger | Root Cause Hint |
|------|---------|-----------------|
| `shared_gpu_failure` | 2+ incidents on same host+gpu_index within same sweep | Check GPU state (VRAM, temperature, driver) |
| `shared_dependency_failure` | 2+ incidents where targets share a DEPENDS_ON edge to a common unhealthy service | Fix the dependency first |
| `shared_host_failure` | 5+ incidents on same host within same sweep | Host resource exhaustion (disk, RAM, network) |
| `shared_volume_failure` | 2+ incidents on services sharing a MOUNTS edge to the same volume | Storage failure (NFS timeout, disk full) |

### Correlation Group Data

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

### API

#### Check for Correlation
```
POST /ops/correlations/check
```
```json
{
  "incidents": ["INC-001", "INC-002", "INC-003"],
  "host": "host-03"
}
```
Returns a correlation group if the incidents share a resource, or null.

### Agent Contract

- When creating multiple incidents in the same sweep, agents MUST call
  `POST /ops/correlations/check` to detect group eligibility
- Agents MUST send a single Slack alert for a correlation group, not per-member
- Individual incidents are still created (for tracking) but are NOT separately alerted
- The group alert MUST include the shared resource and root cause hint
