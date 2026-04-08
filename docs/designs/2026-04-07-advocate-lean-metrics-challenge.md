# Advocate Challenge: Lean Metrics Subsystem

> **Challenger**: Claude Code (Advocate)
> **Date**: 2026-04-07
> **Design Under Review**: `2026-04-07-architect-lean-metrics-design.md`

## Findings

### 1. Trust Ledger Auto-Tune Cannot Work as Designed (HIGH)

`PROMOTION_THRESHOLD` and `PROMOTION_MIN_COUNT` are module-level constants in
`trust_ledger.py` (lines 21-22). Both `record_outcome()` and
`run_promotion_sweep()` read them directly. There is no config indirection.

Writing to an in-memory config dict would have no effect — the functions don't
read from one.

Compounding risk: trust ledger resets counters on promotion. If `min_executions`
is lowered while counters are near zero post-promotion, an action type could
immediately re-qualify with minimal evidence.

**Recommendation**: Drop trust parameter tuning from v1. Add it after a mutable
config layer exists and the counter-reset interaction is addressed.

### 2. Step Timeout Tuning Does Not Affect Existing Plans (HIGH)

The 300s default lives in `PlanStepCreate.timeout` (Pydantic model). On plan
creation, timeout is written to the `ops_plan_steps` row. The step_timeout
reaper reads `row["timeout"]` — the frozen per-row value.

Changing a global default has zero effect on existing plans or executing steps.
It only affects future plans created without an explicit timeout — which agents
rarely do.

**Recommendation**: Clarify that this tunes future defaults only (low impact).
Do not retroactively UPDATE in-flight step timeouts — too dangerous.

### 3. Change Expiry Tuning: Same Frozen-at-Creation Pattern (MEDIUM)

`CHANGE_EXPIRY_HOURS` is read from env at import time (`config.py:45`) and
used to compute `expires_at` at change creation. The expiry task compares
`expires_at < now` — frozen timestamp, not global config.

Additionally, plans have their own `expires_hours` field (default 24, max 72),
completely independent of `CHANGE_EXPIRY_HOURS`. The design conflates these two.

**Recommendation**: Acknowledge future-only impact. Separate plan expiry from
change expiry in the tuning logic.

### 4. Confidence Threshold is Hardcoded in Two Separate Locations (MEDIUM)

The 0.5 threshold appears as magic numbers in:
- `metrics.py:280` — SQL query: `WHERE confidence > 0.5`
- `gap_detection.py:309` — Python: `< 0.5`

Neither reads from config. Auto-tuning would need to modify both simultaneously.
One is a SQL literal.

Further: triage executor assigns confidence as fixed constants (0.85 matched,
0.3 unknown). Tuning a threshold between these two values is a binary switch,
not a gradient.

**Recommendation**: Extract to a single config constant first. Evaluate whether
tuning is meaningful given binary confidence outputs.

### 5. Collector Query Cost is Higher Than Suggested (MEDIUM)

The existing `/ops/metrics` endpoint runs 22+ queries per invocation. The lean
metrics collector adds ~20 more, including percentile computations. SQLite lacks
native percentile functions.

Running 40+ queries every 15 minutes could cause lock contention with other
background tasks that write to the same database.

**Recommendation**: (a) Benchmark existing metrics endpoint latency. (b) Use
`ORDER BY ... LIMIT 1 OFFSET n` for percentiles. (c) Stagger tiers across
cycles if needed. (d) Add circuit breaker: if collection > 10s, skip auto-tuning.

### 6. In-Memory Mutable Config Pattern Does Not Exist (HIGH)

Searched entire `corvus-server/src/` tree. No shared mutable config object
exists. Background tasks use:
- Module-level constants (trust_ledger.py)
- Env vars read at import time (event_cleanup.py)
- Per-row database values (step_timeout.py)

The auto-tuning engine presumes a mutable config singleton that no task reads
from. Building it requires: new config singleton, refactoring all constants into
config reads, testing propagation, atomic revert support.

**Recommendation**: This is the foundational dependency for auto-tuning. Build
it as a prerequisite or defer auto-tuning to v2.

### 7. Snapshot Table Growth Has No Cleanup (MEDIUM)

288 rows/day (~105K/year). The cleanup task (`event_cleanup.py`) has a hardcoded
table list and only prunes `ops_events`, `ops_audit_log`, and `ops_triage_log`.
New tables would not be cleaned up.

**Recommendation**: Add retention policies and prune functions for both
`ops_metrics_snapshots` (90 days) and `ops_metric_adjustments` (365 days).
Add both to `get_table_sizes()`.

## Summary

| # | Finding | Severity | Recommendation |
|---|---------|----------|----------------|
| 1 | Trust auto-tune: no config indirection | High | Defer to v2 |
| 2 | Step timeout: frozen at creation | High | Future-only, low impact |
| 3 | Change expiry: frozen at creation | Medium | Future-only, clarify |
| 4 | Confidence threshold: hardcoded x2 | Medium | Extract to config first |
| 5 | Collector query cost | Medium | Benchmark, stagger, circuit break |
| 6 | No mutable config pattern | High | Foundational prerequisite |
| 7 | No snapshot cleanup | Medium | Add retention policies |

## Recommended Phasing

The Advocate recommends splitting into three phases:

- **v1**: Metrics collection, snapshot storage, API endpoints, MCP tools, schema
  patches, instrumentation, retention policies. No auto-tuning. Delivers 80%
  of the value (visibility into process health) with 20% of the risk.

- **v1.5**: Mutable config singleton. Refactor constants into config reads across
  all background tasks. Extract hardcoded thresholds. This is the bridge.

- **v2**: Auto-tuning engine with dampening, safety rails, revert logic, built
  on the config layer from v1.5.

**Overall**: The metric taxonomy, data model, and API design are sound. The
auto-tuning engine is the right long-term direction but requires infrastructure
that does not exist yet. Ship metrics first, build the config layer, then add
self-tuning. This avoids shipping a self-modifying system atop infrastructure
that cannot actually be modified at runtime.
