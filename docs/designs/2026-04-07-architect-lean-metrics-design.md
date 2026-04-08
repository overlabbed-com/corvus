# Lean Metrics Subsystem Design

> **Author**: Claude Code (Architect)
> **Date**: 2026-04-07
> **Status**: Design approved with Advocate resolutions incorporated
> **Corvus Component**: New subsystem — `lean_metrics` router, models, collector, auto-tuner, `RuntimeConfig`

## Problem Statement

Corvus coordinates multi-agent operations through events, changes, incidents,
plans, and triage runbooks. Each subsystem captures timestamps at key lifecycle
transitions. But there is no concept of **operational metrics** — computed,
time-series measurements that reveal process health, throughput, bottlenecks,
and improvement trends.

Today, the `/ops/metrics` endpoint aggregates counts and averages on demand.
This is a dashboard snapshot, not a metrics system. It cannot answer:

1. Where are my processes slow? (bottleneck identification)
2. Is my capacity keeping up with demand? (takt time vs. throughput)
3. Are things getting better or worse over time? (trend analysis)
4. Can the system tune itself based on observed performance? (self-optimization)

The lean metrics subsystem makes operational measurement a first-class Corvus
primitive, enabling continuous process improvement through data.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Metric storage | Dedicated `ops_metrics_snapshots` table | Structured queries for auto-tuning; event table is wrong shape for time-series aggregation |
| Collection interval | 15 minutes | Balances freshness against query cost; matches existing infra-sync-continuous cadence |
| Auto-tuning | Active with exponential dampening | System must learn and converge; dampening prevents oscillation |
| Safety rails | Bounds + cooldown + rate limit + auto-revert | Self-tuning without guardrails is a runaway feedback loop |
| Existing `/ops/metrics` | Unchanged (backward compatible) | New lean metrics are additive; existing consumers unaffected |
| Instrumentation approach | Patches to existing tables + in-memory task timing | Minimal schema changes; no new tables for raw instrumentation |

## Metric Taxonomy

### Tier 1 — Value Stream Metrics (How fast does work flow?)

| Metric | Definition | Source | Formula |
|--------|-----------|--------|---------|
| `incident_cycle_time` | Detection to resolution | `ops_incidents` | `resolved_at - created_at` (seconds) |
| `incident_queue_time` | Detection to investigation start | `ops_incidents` | `investigating_at - created_at` (new field) |
| `triage_cycle_time` | Triage start to diagnosis | `ops_triage_log` | `outcome_at - timestamp` (seconds) |
| `change_lead_time` | Change window open to close | `ops_changes` | `completed_at - created_at` |
| `plan_lead_time` | Plan creation to completion | `ops_plans` | `completed_at - created_at` |
| `plan_approval_latency` | Draft to approved | `ops_plans` | `approved_at - created_at` |
| `step_execution_time` | Step claimed to result | `ops_plan_steps` | `completed_at - started_at` |
| `trust_promotion_time` | First execution to promotion | `ops_trust_ledger` | `promoted_at - first_seen_at` (new field) |

### Tier 2 — Throughput & Capacity (Can I keep up?)

| Metric | Definition | Source |
|--------|-----------|--------|
| `incident_takt_time` | Avg time between incident arrivals | `ops_incidents` windowed count |
| `resolution_throughput` | Incidents resolved per period | `ops_incidents` windowed count |
| `plan_throughput` | Plans completed per period | `ops_plans` windowed count |
| `step_throughput` | Steps executed per period | `ops_plan_steps` windowed count |
| `triage_throughput` | Triages completed per period | `ops_triage_log` windowed count |
| `wip` | Active incidents + changes + executing plans | Live query across tables |

### Tier 3 — Efficiency & Quality (Am I improving?)

| Metric | Definition | Source |
|--------|-----------|--------|
| `first_time_resolution_rate` | % incidents resolved without escalation | `ops_incidents` |
| `runbook_hit_rate` | % triages with confident diagnosis | `ops_triage_log` (exists) |
| `false_positive_rate` | % incidents closed without remediation | `ops_incidents` (exists) |
| `timeout_rate` | % plan steps that hit timeout | `ops_plan_steps` |
| `rollback_rate` | % plans that trigger rollback | `ops_plans` |
| `siem_forwarding_latency` | P50/P95 of SIEM send duration | SIEM forwarder instrumentation |
| `background_task_duration` | P50/P95 per task cycle | Task loop instrumentation |

## Data Model

### ops_metrics_snapshots Table

```sql
CREATE TABLE IF NOT EXISTS ops_metrics_snapshots (
    id              TEXT PRIMARY KEY,       -- MSNAP-XXXXXXXX
    timestamp       TEXT NOT NULL,          -- when snapshot was computed
    period_start    TEXT NOT NULL,          -- measurement window start
    period_end      TEXT NOT NULL,          -- measurement window end
    tier            TEXT NOT NULL,          -- value_stream / throughput / efficiency
    metrics         TEXT NOT NULL,          -- JSON: all metric values for this tier
    node_id         TEXT DEFAULT 'local',
    hlc_timestamp   TEXT
);

CREATE INDEX IF NOT EXISTS idx_metrics_snapshots_timestamp
    ON ops_metrics_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_snapshots_tier
    ON ops_metrics_snapshots(tier);
```

The `metrics` JSON contains metric values as numbers or percentile objects:
```json
{
    "incident_cycle_time": {"p50": 120.5, "p95": 890.2, "p99": 1800.0, "count": 12},
    "triage_cycle_time": {"p50": 45.0, "p95": 180.0, "p99": 300.0, "count": 8},
    "plan_lead_time": {"p50": 3600.0, "p95": 14400.0, "count": 3}
}
```

### ops_metric_adjustments Table

```sql
CREATE TABLE IF NOT EXISTS ops_metric_adjustments (
    id                  TEXT PRIMARY KEY,   -- MADJ-XXXXXXXX
    timestamp           TEXT NOT NULL,
    parameter           TEXT NOT NULL,      -- e.g., "step_timeout.default"
    old_value           TEXT NOT NULL,       -- previous value (as string)
    new_value           TEXT NOT NULL,       -- new value (as string)
    trigger_metric      TEXT NOT NULL,      -- which metric triggered this
    trigger_value       REAL NOT NULL,      -- the metric value
    trigger_threshold   REAL NOT NULL,      -- the threshold it crossed
    adjustment_number   INTEGER NOT NULL,   -- nth adjustment of this parameter
    dampening_factor    REAL NOT NULL,      -- e^(-k * adjustment_number)
    reasoning           TEXT NOT NULL,      -- human-readable explanation
    reverted            INTEGER NOT NULL DEFAULT 0,  -- 1 if auto-reverted
    reverted_at         TEXT,               -- when it was reverted
    revert_reason       TEXT,               -- why it was reverted
    node_id             TEXT DEFAULT 'local',
    hlc_timestamp       TEXT
);

CREATE INDEX IF NOT EXISTS idx_metric_adjustments_parameter
    ON ops_metric_adjustments(parameter);
CREATE INDEX IF NOT EXISTS idx_metric_adjustments_timestamp
    ON ops_metric_adjustments(timestamp);
```

### Schema Patches to Existing Tables

```sql
-- Incident queue time: when investigation actually starts
ALTER TABLE ops_incidents ADD COLUMN investigating_at TEXT;

-- Trust ledger: when action_type was first seen
ALTER TABLE ops_trust_ledger ADD COLUMN first_seen_at TEXT;

-- Triage: sub-minute resolution timing
ALTER TABLE ops_triage_log ADD COLUMN resolution_time_seconds REAL;
```

Existing columns (`resolution_time_minutes`) retained for backward compatibility.

## Auto-Tuning Engine

### Tunable Parameters

| Parameter | Default | Min | Max | Trigger Metric | Tune Logic |
|-----------|---------|-----|-----|---------------|------------|
| `step_timeout.default` | 300s | 30s | 3600s | `timeout_rate` | If > 15%, increase toward P95 step execution time |
| `step_timeout.reaper_interval` | 60s | 15s | 300s | `background_task.step_timeout.duration_p95` | If reaper takes > 50% of interval, widen |
| `change_expiry.hours` | 4h | 1h | 24h | `change_lead_time_p95` | If P95 exceeds 80% of expiry window, extend |
| `trust.promotion_threshold` | 0.95 | 0.80 | 0.99 | `rollback_rate` | If rollback on AUTO actions > 10%, tighten |
| `trust.min_executions` | 20 | 5 | 100 | `trust_promotion_time_p50` | If median > 30d and 100% success, lower |
| `triage.confidence_threshold` | 0.5 | 0.2 | 0.9 | `runbook_hit_rate` | If hit rate < 60%, lower; if > 90%, raise |

### Dampening Mechanics

```
actual_correction = calculated_correction * e^(-k * adjustment_number)
```

Where `k = 0.1` (configurable). Dampening factor by adjustment number:

| Adj # | Factor | Correction Applied |
|-------|--------|-------------------|
| 1 | 0.90 | 90% |
| 5 | 0.61 | 61% |
| 10 | 0.37 | 37% |
| 20 | 0.14 | 14% |
| 30 | 0.05 | 5% |

**Seasonal reset**: If a parameter hasn't been adjusted in 7+ days, reset
`adjustment_number` to 0. This allows re-learning after environment changes.

### Safety Rails

1. **Min/max bounds** on every parameter. No value escapes its rails.
2. **Rate limit**: max 1 adjustment per parameter per collection cycle (15 min).
3. **Cooldown**: after adjusting, skip evaluation for 3 cycles (45 min).
4. **Auto-revert**: if trigger metric worsens 2 consecutive cycles post-adjustment,
   revert and log reason. Circuit breaker.
5. **Event emission**: all adjustments emit `metrics.adjustment` events for SIEM.

### Collection Cycle

Background task `run_metrics_collector_loop` every 15 minutes:

1. Compute all Tier 1/2/3 metrics from source tables
2. Store snapshot rows in `ops_metrics_snapshots` (one per tier)
3. Compare each tunable parameter's trigger metric against threshold
4. For threshold breaches: compute correction → apply dampening → check
   bounds → check cooldown → apply if valid
5. Log adjustment in `ops_metric_adjustments`
6. Emit `metrics.snapshot` and `metrics.adjustment` events

## API

### Lean Metrics Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ops/lean-metrics` | Current snapshot — all tiers, latest values |
| `GET` | `/ops/lean-metrics/history` | Time-series with lookback (`?hours=24&tier=value_stream`) |
| `GET` | `/ops/lean-metrics/throughput` | Counts bucketed by hour/day (`?entity=incidents&hours=168`) |
| `GET` | `/ops/lean-metrics/bottlenecks` | Top N slowest processes ranked by cycle time deviation |
| `GET` | `/ops/lean-metrics/adjustments` | Auto-tune audit trail (`?parameter=step_timeout.default`) |
| `GET` | `/ops/lean-metrics/convergence` | Per-parameter convergence status |

### MCP Tools

| Tool | Purpose | Consumer |
|------|---------|----------|
| `ops_lean_metrics` | Current lean metrics snapshot | CC sessions |
| `ops_bottlenecks` | Where are processes slow? | CC (the operator, Planner) |
| `ops_throughput` | Demand vs. capacity | CC (Planner) |
| `ops_convergence` | Is auto-tuning converging? | CC (Sentinel) |

## Instrumentation Patches

### Background Task Self-Timing

Every existing task loop gets a timing wrapper:
```python
start = time.monotonic()
count = await do_the_work()
elapsed_ms = (time.monotonic() - start) * 1000
```

Elapsed time stored in a shared in-memory `task_metrics` dict, read by the
collector each cycle. No new tables for raw timing — snapshotted into
`ops_metrics_snapshots`.

### SIEM Forwarder Latency

Track `duration_ms` per `_send()` call in base adapter. Accumulate into a list,
compute P50/P95 at snapshot time. In-memory, read by collector.

### Triage Timing Upgrade

Triage outcome endpoint computes `resolution_time_seconds` (REAL) alongside
existing `resolution_time_minutes` (INTEGER, kept for backward compat).

### Incident Queue Time

When incident status transitions to `investigating`, set
`investigating_at = now`. Collector computes queue time from delta.

### Trust Ledger First-Seen

When a new `action_type` is first recorded, set `first_seen_at = now`.
Collector computes time-to-trust from delta with `promoted_at`.

## Advocate Resolution: RuntimeConfig Singleton

The Advocate challenge identified that the auto-tuning engine presumes a mutable
config layer that does not exist in Corvus. All tunable parameters are either
module-level constants, Pydantic model defaults, or magic numbers in SQL.

### Resolution: Build `RuntimeConfig` as a prerequisite

A new `RuntimeConfig` class in `corvus-server/src/config.py`:

```python
class RuntimeConfig:
    """Mutable runtime configuration with atomic get/set/revert.
    
    Background tasks and routers read tunable parameters from here
    instead of module-level constants. The auto-tuner writes here.
    Defaults match the original hardcoded values.
    """
    _instance = None
    _values: dict[str, float | int | str]
    _defaults: dict[str, float | int | str]
    
    @classmethod
    def get(cls, key: str) -> float | int | str: ...
    
    @classmethod
    def set(cls, key: str, value: float | int | str) -> None: ...
    
    @classmethod
    def revert(cls, key: str) -> None: ...  # restore to default
    
    @classmethod
    def snapshot(cls) -> dict: ...  # current values for metrics
```

### Constants to Refactor

| Current Location | Constant | RuntimeConfig Key |
|-----------------|----------|-------------------|
| `trust_ledger.py:21` | `PROMOTION_THRESHOLD = 0.95` | `trust.promotion_threshold` |
| `trust_ledger.py:22` | `PROMOTION_MIN_COUNT = 20` | `trust.min_executions` |
| `config.py:45` | `CHANGE_EXPIRY_HOURS = 4` | `change_expiry.hours` |
| `metrics.py:280` | `confidence > 0.5` (SQL literal) | `triage.confidence_threshold` |
| `gap_detection.py:309` | `< 0.5` (Python literal) | `triage.confidence_threshold` |
| `models/plans.py:19` | `timeout: int = 300` | `step_timeout.default` |

After refactoring, `record_outcome()` reads `RuntimeConfig.get("trust.promotion_threshold")`
instead of `PROMOTION_THRESHOLD`. Same pattern for all other consumers.

### Acknowledged Limitations

- **Step timeout tuning affects future plans only.** Per-step timeout is frozen
  at creation in `ops_plan_steps`. Tuning the default is still valuable — the
  metric reveals whether 300s is the right default.
- **Change expiry tuning affects future changes only.** `expires_at` is frozen
  at change creation. Plan expiry (`expires_hours`) is a separate parameter.
- **Triage confidence is binary (0.3/0.85).** Tuning the threshold between these
  two values acts as a noise filter, not a gradient. Acceptable for v1; per-runbook
  confidence scoring would improve this in the future.

### Additional Resolutions

- **Query cost**: Add circuit breaker — if collection cycle > 10s, skip auto-tuning
  for that cycle and emit `metrics.anomaly` event.
- **Snapshot cleanup**: Add `METRICS_SNAPSHOT_RETENTION_DAYS = 90` and
  `METRICS_ADJUSTMENT_RETENTION_DAYS = 365`. Register prune functions in
  `run_cleanup_loop()`. Add both tables to `get_table_sizes()`.

## Event Types

| Type | When | Severity |
|------|------|----------|
| `metrics.snapshot` | Metrics collection cycle completed | info |
| `metrics.anomaly` | Metric crossed threshold | warning |
| `metrics.adjustment` | Auto-tune applied a correction | warning |
| `metrics.revert` | Auto-tune reverted a correction | warning |
| `metrics.converged` | Parameter dampening factor < 0.05 | info |

OCSF mapping: Compliance Finding (2003), consistent with gap events.

## Risk Assessment

| Risk | Blast Radius | Reversibility | Mitigation |
|------|-------------|---------------|------------|
| Auto-tune oscillation | Multi-service (if timeout/trust affected) | Easy (auto-revert) | Dampening + cooldown + bounds + circuit breaker |
| Metric computation expensive on large tables | Contained (Corvus only) | Trivial (reduce frequency) | Windowed queries, indexes, 15-min interval |
| Schema migration breaks existing queries | Multi-service | Moderate | ALTER TABLE ADD COLUMN (additive only), keep old columns |
| Collector task crashes | Contained | Easy (restart loop) | Same try/except pattern as all other background tasks |
| Bad metric data feeds auto-tune | Multi-service | Moderate | Auto-revert on worsening, min/max bounds prevent extremes |
| Seasonal reset re-learns wrong lesson | Contained | Easy (revert) | 7-day threshold; adjustment history shows pattern |

## Rollback Plan

The lean metrics subsystem is additive — new tables, new router, new background
task, new MCP tools. Removal requires dropping `ops_metrics_snapshots` and
`ops_metric_adjustments` tables, removing the router and task registrations, and
removing MCP tool functions. Schema patches (ADD COLUMN) are permanent but
harmless — unused columns don't affect existing queries.

Auto-tune adjustments write to in-memory config, not to database config. If the
subsystem is removed, all parameters revert to their defaults on next restart.

## Dependencies

- `ops_incidents` (cycle time, queue time, throughput)
- `ops_triage_log` (triage timing, hit rate)
- `ops_changes` (lead time, WIP)
- `ops_plans` / `ops_plan_steps` (plan metrics, timeout rate)
- `ops_trust_ledger` (promotion time, threshold tuning)
- `ops_events` (event emission for snapshots/adjustments)
- SIEM forwarder (latency instrumentation)
- All background tasks (self-timing instrumentation)
- Existing MCP server (`mcp_server.py`)
