# OCSF Data Model Mapping — Ops Graph Explorer Phase 1

> Agent: Architect
> Workspace: automation
> Project: ops-graph-explorer
> Risk Level: AUTO (design only)
> Generated: 2026-03-29

## Summary

Maps the SOP event stream and CMDB to OCSF (Open Cybersecurity Schema Framework)
event classes for audit-grade, graph-traversable, SIEM-portable operational data.
Every incident, change, remediation, and dependency chain becomes OCSF-compliant
and graph-navigable in Splunk.

## OCSF Event Class Mapping

### Core Mapping: SOP Events → OCSF Classes

| SOP Event Type | OCSF Class | Class UID | Rationale |
|---------------|-----------|-----------|-----------|
| `incident.opened` | Incident Finding | 2005 | Detected issue with severity, target, investigation |
| `incident.investigating` | Incident Finding | 2005 | Status update on same finding (activity_id: Update) |
| `incident.resolved` | Incident Finding | 2005 | Resolution with fix details (activity_id: Close) |
| `incident.escalated` | Incident Finding | 2005 | Escalation with reason (activity_id: Other) |
| `change.started` | Device Config State Change | 5019 | Planned infrastructure modification |
| `change.completed` | Device Config State Change | 5019 | Change window closed, outcome recorded |
| `change.failed` | Device Config State Change | 5019 | Change failed, rollback needed |
| `remediation.restart` | Remediation Activity | 7001 | Container restart action |
| `remediation.config_fix` | Remediation Activity | 7001 | Configuration correction |
| `remediation.credential_rotation` | Remediation Activity | 7001 | Credential rotation |
| `sweep.completed` | Scan Activity | 6007 | Health sweep cycle result |
| `sweep.anomaly` | Detection Finding | 2004 | Anomaly detected during sweep |
| `action.approved` | API Activity | 6003 | Human approval of agent action |
| `action.denied` | API Activity | 6003 | Human denial of agent action |
| `session.started` | Application Lifecycle | 6002 | Agent session lifecycle |
| `session.ended` | Application Lifecycle | 6002 | Agent session lifecycle |
| `gap:*` (blind spots) | Compliance Finding | 2003 | System capability gap detected |

### CMDB → OCSF Inventory

| CMDB Entity | OCSF Class | Class UID | Frequency |
|-------------|-----------|-----------|-----------|
| Service record | Device Inventory Info | 5001 | On change + daily snapshot |
| Service dependencies | Device Inventory Info | 5001 | Embedded as `connected_to` array |
| Service config baseline | Device Config State | 5002 | On change |

## OCSF Event Structure

### Base Event (all SOP events)

```json
{
  "class_uid": 2005,
  "class_name": "Incident Finding",
  "category_uid": 2,
  "category_name": "Findings",
  "severity_id": 3,
  "severity": "High",
  "activity_id": 1,
  "activity_name": "Create",
  "time": "2026-03-29T18:10:01.412Z",
  "message": "Container 'vllm-primary' unhealthy on host-01 — CUDA OOM",

  "metadata": {
    "version": "1.3.0",
    "product": {
      "name": "Unified Ops Protocol",
      "vendor_name": "Corvus",
      "version": "1.0.0"
    },
    "logged_time": "2026-03-29T18:10:01.412Z"
  },

  "actor": {
    "agent": {
      "name": "ops-agent",
      "type": "AI Ops Agent",
      "uid": "ops-agent:health_sweep"
    }
  },

  "finding_info": {
    "uid": "INC-042",
    "title": "CUDA OOM on vllm-primary",
    "desc": "GPU VRAM exhausted. Diagnosis via triage-inference.yaml runbook.",
    "types": ["gpu_oom"],
    "created_time": "2026-03-29T18:10:01.412Z"
  },

  "resources": [
    {
      "uid": "vllm-primary",
      "name": "vllm-primary",
      "type": "container",
      "owner": { "name": "host-01" },
      "labels": ["service_type:inference", "stack:ai", "critical:false"]
    }
  ],

  "evidences": [
    {
      "data": {
        "runbook": "triage-inference.yaml",
        "diagnosis": "gpu_oom",
        "confidence": 0.85,
        "gpu_vram_pct": 99.5,
        "investigation_duration_ms": 1200
      }
    }
  ],

  "observables": [
    { "name": "target", "type": "hostname", "value": "vllm-primary" },
    { "name": "host", "type": "hostname", "value": "host-01" }
  ],

  "unmapped": {
    "sop_event_type": "incident.opened",
    "sop_event_id": "83b414ea...",
    "related_change_id": null,
    "related_incident_id": "INC-042",
    "parent_event_id": null,
    "workstream": null,
    "trust_tier": "ESCALATE"
  }
}
```

### Graph Edge Metadata (in `unmapped` for traversal)

Every OCSF event carries relationship edges in `unmapped`:

```json
{
  "unmapped": {
    "sop_event_id": "evt-001",
    "parent_event_id": "evt-000",
    "related_incident_id": "INC-042",
    "related_change_id": "CHG-015",
    "related_problem_id": "PRB-003",
    "caused_by": "evt-000",
    "triggered": ["evt-002", "evt-003"],
    "approved_by": "operator:slack:1711735801",
    "remediated_by": "evt-004",
    "verified_by": "evt-005"
  }
}
```

These edges enable Splunk SPL graph queries:
```spl
| spath unmapped.related_incident_id
| search unmapped.related_incident_id="INC-042"
| sort time
```

### CMDB Inventory Event (Device Inventory Info, 5001)

```json
{
  "class_uid": 5001,
  "class_name": "Device Inventory Info",
  "activity_id": 1,
  "activity_name": "Log",
  "time": "2026-03-29T00:00:00Z",

  "device": {
    "uid": "vllm-primary",
    "name": "vllm-primary",
    "type": "container",
    "hostname": "host-01",
    "os": { "name": "Linux" },
    "hw_info": {
      "gpu": { "vram_mb": 100352, "model": "RTX PRO 6000 Max-Q" }
    }
  },

  "unmapped": {
    "service_type": "inference",
    "stack": "ai",
    "critical": false,
    "dependencies": ["litellm"],
    "connected_to": [
      { "uid": "litellm", "relationship": "depends_on" },
      { "uid": "milvus-standalone", "relationship": "serves" }
    ],
    "baseline_behavior": {
      "expected_restarts_per_day": 0,
      "expected_startup_time_seconds": 600
    }
  }
}
```

## Transformation Architecture

```
SOP Event (custom JSON)
    ↓
OCSF Transformer (Admin API middleware)
    ↓
OCSF Event (standard JSON)
    ↓ ← graph edges injected here
Splunk HEC (fire-and-forget)
    ↓
Splunk Index: idx_sop_ocsf
    ↓
Custom Splunk App (graph explorer + audit queries)
```

The transformer runs in Admin API's `_forward_to_splunk()` function — currently
sends raw events, will now transform to OCSF first.

## Implementation Approach

1. **OCSF transformer module** in Admin API: `ocsf_transformer.py`
   - Maps SOP event type → OCSF class_uid
   - Builds OCSF event structure with metadata, actor, resources, evidences
   - Injects graph edge metadata in `unmapped`
   - Returns OCSF-compliant JSON

2. **Modify `_forward_to_splunk()`** to call transformer before HEC send
   - `sourcetype: ocsf` (not `sop:event`)
   - `index: idx_sop_ocsf`

3. **CMDB inventory indexer**: periodic job (Prefect or Admin API cron)
   - Exports full CMDB as OCSF Device Inventory events
   - Includes dependency edges in `unmapped.connected_to`
   - Daily snapshot + on-change delta

4. **Splunk index + field extractions**:
   - `idx_sop_ocsf` index with OCSF field extractions
   - Lookup table: `cmdb_dependencies.csv` for graph joins
   - Saved searches for common traversal patterns

## Risk Assessment

| Component | Blast Radius | Reversibility |
|-----------|-------------|---------------|
| OCSF transformer | None (data format) | Trivial (revert to raw) |
| HEC forwarding change | Contained (Splunk only) | Easy (change sourcetype back) |
| CMDB inventory indexer | None (read-only) | Trivial (stop job) |
| Splunk index | Contained (Splunk) | Easy (delete index) |

## Portability

The OCSF transformation is the portability layer. Any SIEM that supports OCSF
(AWS Security Lake, Azure Sentinel, Google Chronicle, Elastic) can consume the
same events. The Splunk app is the first consumer, not the only one.
