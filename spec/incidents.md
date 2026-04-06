# Incident Lifecycle

Incidents are trackable records of operational issues. Agents create incidents
when they detect problems — not just log messages or markdown reports. This
enables correlation, resolution tracking, and gap detection.

## Lifecycle

```
open → investigating → resolved
open → investigating → escalated → resolved
open → resolved (auto-resolved)
```

## API

### Create Incident
```
POST /ops/incidents
```
```json
{
  "target": "vllm-primary",
  "title": "CUDA OOM on vllm-primary",
  "description": "GPU VRAM exhausted during inference. Detected via health sweep.",
  "severity": "critical",
  "detected_by": "ops-agent:health_sweep"
}
```

### List Incidents
```
GET /ops/incidents?status=open&target=vllm-primary&severity=critical
```

### Get Incident
```
GET /ops/incidents/{id}
```

### Update Incident
```
PATCH /ops/incidents/{id}
```
```json
{
  "status": "resolved",
  "root_cause": "GPU memory leak in vLLM batch scheduler",
  "investigation_summary": "nvidia-smi showed 99.5% VRAM, logs showed OOM at batch 847",
  "remediation_applied": "Restarted container after confirming VRAM cleared"
}
```

## Gap Detection on Resolution

When an incident is resolved, Corvus automatically checks for gaps:

| Condition | Gap Pattern | Workstream |
|-----------|------------|------------|
| No root cause identified | `gap:accuracy:unclassifiable:{target}` | CI |
| Resolution time > 2x baseline | `gap:efficiency:slow-resolution:{target}` | CI |
| No remediation applied | `gap:autonomy:manual-resolution:{target}` | CI |

Gaps are created as problem records and deduplicated — repeat failures on the
same target append to `correlated_incidents` instead of creating duplicates.

## Severity Levels

| Level | Meaning | Target Status Effect |
|-------|---------|---------------------|
| `low` | Minor issue, no impact | CAUTION |
| `medium` | Degraded service | CAUTION |
| `high` | Significant impact | STOP |
| `critical` | Service down or data at risk | STOP |
