# Advocate Challenge: Plan Execution Subsystem

> **Challenger**: Claude Code (Advocate)
> **Date**: 2026-04-07
> **Design Under Review**: `2026-04-07-architect-plan-execution-design.md`

## Findings

### 1. Rollback-of-rollback failure path (LOW)

If a rollback step itself fails, the plan transitions to `blocked`. This is the
correct answer — recursive rollback is worse. The `blocked` state honestly admits
the system needs a human. Plan status makes the partial state visible.

**Action**: None. Design already handles this correctly.

### 2. Step timeout detection mechanism (MEDIUM)

The design mentions "step timeout -> re-queued as pending" but does not specify
who detects timeouts. An agent claiming a step and crashing leaves it in
`executing` state indefinitely, blocking the DAG.

**Recommendation**: Add a background task (like existing change window expiry)
that scans for steps in `executing` state past their timeout. Transition to
`pending` with `retry_count + 1`. If `retry_count >= max_retries`, treat as
failure per the step's `failure_policy`.

### 3. @host fan-out expansion responsibility (LOW)

The `tetragon@host-01` convention is a string format, not a schema feature.
Who expands a logical target into host-scoped targets?

**Recommendation**: CC expands at plan creation time. The plan is the contract —
what you see is what executes. Fleet membership comes from CMDB queries during
plan construction. The server stays topology-unaware. Verbosity is acceptable
for a 4-host fleet.

### 4. Plan expiry window (LOW)

24h auto-expiry for `approved` plans may be too restrictive. Plans created during
weekday sessions for weekend execution would expire before use.

**Recommendation**: Make plan expiry configurable at creation time. Default 24h,
maximum 72h. Same pattern as change window `auto_expire`.

### 5. No plan templates (LOW — DEFER)

Every plan is a one-off. Fleet operations are repetitive. Without templates, CC
rebuilds the same structure every time.

**Verdict**: Acceptable for v1. Templates are a natural v2 feature if plans
become repetitive. YAGNI applies.

### 6. plan.execute not trust-gated (MEDIUM)

The design adds plan lifecycle events but does not gate the *act of starting
execution*. A low-trust agent could call `ops_execute_plan()` on a plan
containing pre-approved AUTO steps, effectively bypassing trust controls.

**Recommendation**: Add `plan.execute` as a trust ledger action type. The right
to start a plan is distinct from the right to execute individual steps. Plan
creation (drafts) remains ungated.

### 7. Corvus downtime risk (LOW)

Plans make Corvus load-bearing for in-flight mutations. But Corvus already owns
change windows and events. Steps in `executing` state when Corvus goes down will
timeout and re-queue when it recovers. No new risk surface beyond existing.

**Action**: None. Existing risk, not new.

## Summary

| # | Finding | Severity | Recommendation |
|---|---------|----------|----------------|
| 1 | Rollback failure path | Low | Design handles correctly |
| 2 | Step timeout detection | Medium | Add background reaper task |
| 3 | Fan-out expansion | Low | CC expands, document convention |
| 4 | Plan expiry window | Low | Configurable, 72h max |
| 5 | No templates | Low | Defer to v2 |
| 6 | plan.execute trust gating | Medium | Add to trust ledger |
| 7 | Corvus downtime | Low | Existing risk |

**Overall**: Design is sound. Two medium findings (step timeout reaper,
plan.execute trust gating) should be incorporated before implementation.
No blocking concerns.
