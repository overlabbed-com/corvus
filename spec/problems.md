# Problem Management + Gap Detection

Problems represent recurring patterns and systemic issues. In Corvus,
**gaps ARE problems** — the same lifecycle handles both operational problems
and detection blind spots.

## Lifecycle

```
identified → investigating → resolved
identified → investigating → deferred
```

## Problem Types

### Operational Problems
Created by agents when they detect recurring patterns across multiple incidents.

### Gap Problems (Blind Spot Detection)
Auto-created by Corvus when operational loops detect coverage gaps.

| Gap Pattern | Source | Workstream |
|------------|--------|-----------|
| `gap:accuracy:unclassifiable:{target}` | Incident resolved without root cause | CI |
| `gap:accuracy:wrong-recommendation` | Applied fix differs from runbook | CI |
| `gap:efficiency:slow-resolution:{target}` | Resolution > 2x baseline | CI |
| `gap:autonomy:manual-resolution:{target}` | No automated remediation | CI |
| `gap:coverage:no-runbook:{service_type}` | Triage found no matching runbook | NFI |
| `gap:coverage:untyped-service:{name}` | CMDB service has no service_type | NFI |
| `gap:coverage:generic-fallback` | Generic triage used instead of specific | NFI |
| `gap:monitoring:unseen-service` | Service not seen in 7 days | NFI |
| `gap:security:stale-finding` | Threat finding unaddressed > 30d | CI |
| `gap:autonomy:stuck-escalation` | Action type never promotes in trust ledger | CI |

## Workstream Routing

- **CI** (Continuous Improvement): Existing capability needs tuning
- **NFI** (New Feature Implementation): New capability needed

## API

### Create Problem
```
POST /ops/problems
```
```json
{
  "title": "Unclassifiable failure on vllm-primary",
  "pattern": "gap:accuracy:unclassifiable:vllm-primary",
  "root_cause": "Agent couldn't determine root cause",
  "recommended_fix": "CI: Add CUDA OOM diagnosis pattern to inference runbook",
  "severity": "medium",
  "workstream": "CI"
}
```

### List Problems
```
GET /ops/problems?status=identified&workstream=CI&pattern=gap:accuracy
```

### Update Problem
```
PATCH /ops/problems/{id}
```

### Correlate Incident to Problem
```
POST /ops/problems/correlate
```
```json
{
  "incident_id": "INC-A1B2C3D4",
  "problem_id": "PRB-E5F6G7H8"
}
```

This bidirectionally links the incident and problem. The incident gets
`correlated_to_problem` set, and the problem's `correlated_incidents`
array is appended.

## Deduplication

Gap detection deduplicates by pattern. If a gap with the same pattern
already exists and is unresolved, the new incident is appended to
`correlated_incidents` instead of creating a duplicate problem.
