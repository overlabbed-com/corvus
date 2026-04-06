# Autonomous Ops Agent — Corvus Integration Example

This example shows how an autonomous infrastructure agent integrates with Corvus.
The patterns here apply to any agent built on any framework.

## What This Agent Does

- **Health sweeps** — tiered monitoring across containers, GPUs, storage, DNS
- **FMEA triage** — service-type-aware investigation using Corvus runbooks
- **Graduated autonomy** — trust ledger tracks reliability per action type
- **Remediation** — restarts, escalation, human-in-the-loop via chat
- **CMDB discovery** — auto-registers new containers in Corvus CMDB
- **Blind spot detection** — creates gap:* problem records for unclassifiable failures

## Sweep Cycle

```
1. Refresh change windows -> GET /ops/changes/active
2. Run health checks across all domains
3. For each unhealthy target:
   a. Check if suppressed by change window -> skip if yes
   b. Query CMDB for service_type -> GET /ops/cmdb/{name}
   c. Select triage runbook by service_type
   d. Run investigation -> diagnosis
   e. Create incident -> POST /ops/incidents
   f. Emit event -> POST /ops/events
   g. Correlate incidents -> POST /ops/problems/correlate
   h. If gap detected -> POST /ops/problems (gap:* pattern)
4. Report sweep results -> POST /ops/events (sweep.completed)
```

## Key Patterns

### 1. Always check before acting
```python
status = await corvus.get(f"/ops/events/targets/{target}/status")
if status["recommendation"] == "STOP":
    return  # Another agent is already working on this
```

### 2. Always emit events for state changes
```python
await corvus.post("/ops/events", json={
    "source": "my-agent",
    "type": "remediation.restart",
    "target": container_name,
    "severity": "warning",
    "data": {"summary": "Restarted due to OOM"}
})
```

### 3. Create incidents, not just alerts
```python
await corvus.post("/ops/incidents", json={
    "target": container_name,
    "description": "Container unhealthy — CUDA OOM detected",
    "severity": "critical",
    "detected_by": "my-agent:health_sweep"
})
```

### 4. Report blind spots
```python
await corvus.post("/ops/problems", json={
    "title": f"Unclassifiable failure on {target}",
    "pattern": f"gap:accuracy:unclassifiable:{target}",
    "root_cause": "Agent couldn't determine root cause",
    "recommended_fix": "Add new diagnosis rule or runbook hint"
})
```
