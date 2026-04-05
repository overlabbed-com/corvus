# NemoClaw — Corvus Agent Integration (Customer Zero)

NemoClaw is an autonomous AI ops agent for the TMT Homelab. It was the first agent
built on the Corvus protocol and serves as the reference implementation for how
agents integrate with Corvus.

## What NemoClaw Does

- **Health sweeps** — tiered monitoring (5-30 min) across containers, GPUs, ZFS, DNS, IoT
- **FMEA triage** — service-type-aware investigation using Corvus runbooks
- **Graduated autonomy** — trust ledger (BLOCKED → ESCALATE → NOTIFY → AUTO)
- **Remediation** — restarts, escalation, Slack-based human-in-the-loop
- **Slack bot** — interactive buttons, LLM conversations, investigation threads
- **CMDB discovery** — auto-registers new containers in Corvus CMDB
- **Blind spot detection** — creates gap:* problem records when it can't classify failures

## How NemoClaw Uses Corvus

### On every sweep cycle:
```
1. Refresh change windows → GET /ops/changes/active
2. Run health checks across all domains
3. For each unhealthy target:
   a. Check if suppressed by change window → skip if yes
   b. Query CMDB for service_type → GET /ops/cmdb/{name}
   c. Select triage runbook by service_type
   d. Run investigation → diagnosis
   e. Create incident → POST /ops/incidents
   f. Emit event → POST /ops/events
   g. Correlate incidents → POST /ops/problems/correlate
   h. If gap detected → POST /ops/problems (gap:* pattern)
4. Report sweep results → POST /ops/events (sweep.completed)
```

### On remediation:
```
1. Check target status → GET /ops/events/targets/{target}/status
2. Execute remediation (restart, config fix, etc.)
3. Emit event → POST /ops/events (remediation.restart)
4. Verify post-remediation health
5. Update incident → PATCH /ops/incidents/{id}
```

### On CMDB discovery (every infrastructure sweep):
```
1. List live containers from infrastructure
2. Compare against CMDB → GET /ops/cmdb
3. Register new services → POST /ops/cmdb/register
4. Update last_seen for known services → PATCH /ops/cmdb/{name}
5. Flag untyped services → POST /ops/problems (gap:coverage:untyped-service)
6. Flag unseen services → POST /ops/problems (gap:monitoring:unseen-service)
```

## Integration Architecture

```
NemoClaw (Python, standalone container)
    │
    ├── HTTP → Corvus API (ops state, CMDB, events, incidents)
    ├── HTTP → Infrastructure APIs (Docker, GPU, DNS, IoT)
    ├── HTTP → LLM backend (for conversational diagnosis)
    ├── WebSocket → Slack (bot interactions)
    └── HTTP → Splunk HEC (direct log forwarding)
```

NemoClaw is NOT part of Corvus. It's a consumer that speaks the protocol.
Any agent built on any framework can replicate this integration pattern.

## Key Patterns for Other Agents

### 1. Always check before acting
```python
# Before ANY action on a target:
status = await corvus_api.get(f"/ops/events/targets/{target}/status")
if status["recommendation"] == "STOP":
    # Another agent is working on this — don't interfere
    return
```

### 2. Always emit events for state changes
```python
# After any remediation:
await corvus_api.post("/ops/events", json={
    "source": "my-agent",
    "type": "remediation.restart",
    "target": container_name,
    "severity": "warning",
    "data": {"summary": "Restarted due to OOM"}
})
```

### 3. Create incidents, not just alerts
```python
# When you detect a problem:
await corvus_api.post("/ops/incidents", json={
    "target": container_name,
    "description": "Container unhealthy — CUDA OOM detected",
    "severity": "critical",
    "detected_by": "my-agent:health_sweep"
})
```

### 4. Report your blind spots
```python
# When you can't classify a failure:
await corvus_api.post("/ops/problems", json={
    "title": f"Unclassifiable failure on {target}",
    "pattern": f"gap:accuracy:unclassifiable:{target}",
    "root_cause": "Agent couldn't determine root cause",
    "recommended_fix": "CI: Add new diagnosis rule or runbook hint"
})
```

## Source Code

NemoClaw source lives in the TMT Homelab GitOps repo (private):
`homelab-gitops/stacks/dockp04-automation/nemoclaw/`

11,300 lines of Python, 540+ tests, 68 playbooks.
