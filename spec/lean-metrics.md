# Lean Metrics

Lean operational metrics measure how efficiently work flows through Corvus.
Metrics are computed every 15 minutes and stored as time-series snapshots.

## Metric Taxonomy

### Tier 1: Value Stream (how fast does work flow?)

| Metric | Computation | Unit |
|--------|------------|------|
| `incident_cycle_time` | resolved_at - created_at | seconds |
| `incident_queue_time` | investigating_at - created_at | seconds |
| `triage_cycle_time` | resolution_time_seconds | seconds |
| `change_lead_time` | completed_at - created_at | seconds |
| `plan_lead_time` | completed_at - created_at | seconds |
| `plan_approval_latency` | approved_at - created_at | seconds |
| `step_execution_time` | completed_at - started_at | seconds |
| `trust_promotion_time` | promoted_at - first_seen_at | seconds |

### Tier 2: Throughput & Capacity (demand vs. capacity)

| Metric | Computation | Unit |
|--------|------------|------|
| `incidents_resolved` | COUNT(resolved in window) | count |
| `plans_completed` | COUNT(completed in window) | count |
| `steps_executed` | COUNT(completed steps in window) | count |
| `triages_completed` | COUNT(non-pending in window) | count |
| `incident_takt_time` | window_seconds / resolved_count | seconds |
| `triage_takt_time` | window_seconds / triage_count | seconds |
| `wip` | active incidents + changes + executing plans | count |

### Tier 3: Efficiency & Quality (how well is the system working?)

| Metric | Computation | Unit |
|--------|------------|------|
| `triage_hit_rate` | confidence > threshold / total | percent |
| `timeout_rate` | timed_out_steps / total_steps | percent |
| `rollback_rate` | rolled_back_plans / total_plans | percent |
| `escalation_rate` | escalated_triages / total_triages | percent |
| `task_stats` | Background task timing (p50/p95/max) | ms |
| `siem_latency` | SIEM forward latency (p50/p95) | ms |

## Auto-Tuning

Corvus self-optimizes 6 parameters using exponential dampening:

`actual_correction = calculated_correction * e^(-k * adjustment_number)`

Where k=0.1. Early adjustments are bold (~90% of calculated), converging
toward zero as the system learns.

### Tunable Parameters

| Parameter | Default | Bounds | Trigger |
|-----------|---------|--------|---------|
| `step_timeout.default` | 300s | 30-3600 | timeout_rate > 15% |
| `step_timeout.reaper_interval` | 60s | 15-300 | timeout_rate > 15% |
| `change_expiry.hours` | 4h | 1-24 | change_lead_time.p95 > 4h |
| `trust.promotion_threshold` | 0.95 | 0.80-0.99 | rollback_rate > 20% |
| `trust.min_executions` | 20 | 5-100 | rollback_rate > 20% |
| `triage.confidence_threshold` | 0.5 | 0.2-0.9 | escalation_rate > 30% |

### Safety Rails

- Min/max bounds on all parameters (clamped automatically)
- 45-minute cooldown between adjustments per parameter
- Auto-revert if metric worsens for 2 consecutive cycles
- Circuit breaker: skip tuning if collection takes > 10 seconds

## API

### Current Snapshot
```
GET /ops/lean-metrics
```

### History
```
GET /ops/lean-metrics/history?hours=24&tier=value_stream
```

### Throughput
```
GET /ops/lean-metrics/throughput?entity=incidents&hours=168
```

### Bottlenecks
```
GET /ops/lean-metrics/bottlenecks?top_n=5
```

### Adjustments
```
GET /ops/lean-metrics/adjustments?parameter=step_timeout.default&limit=50
```

### Convergence
```
GET /ops/lean-metrics/convergence
```

## MCP Tools

| Tool | Purpose |
|------|---------|
| `ops_lean_metrics` | Current snapshot (session start) |
| `ops_bottlenecks` | Where to focus improvement |
| `ops_throughput` | Demand vs capacity by entity |
| `ops_convergence` | Auto-tuning learning status |

## Event Types

| Type | When | Severity |
|------|------|----------|
| `metrics.snapshot` | Collection cycle completed | info |
| `metrics.anomaly` | Metric crossed threshold | warning |
| `metrics.adjustment` | Auto-tune applied correction | warning |
| `metrics.revert` | Auto-tune reverted correction | warning |
| `metrics.converged` | Parameter dampening < 0.05 | info |

## Retention

| Table | Retention | Configurable Via |
|-------|-----------|-----------------|
| `ops_metrics_snapshots` | 90 days | `CORVUS_METRICS_SNAPSHOT_RETENTION_DAYS` |
| `ops_metric_adjustments` | 365 days | `CORVUS_METRICS_ADJUSTMENT_RETENTION_DAYS` |
