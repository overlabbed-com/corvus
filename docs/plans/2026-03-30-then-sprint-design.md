# THEN Sprint Design — Issues #5, #6, #18

> Approved: 2026-03-30
> Issues: #5 (Signal Quality), #6 (Blind Spot Detection), #18 (CC Governance Rules)
> Parallel execution: 3 independent branches

---

## Issue #5: Signal Quality (<20% False Positive Rate)

### New: `src/tasks/baseline_checker.py`

Pre-incident filter checking CMDB `baseline_behavior` before creating incidents.
`check_baseline(target, event_type) -> bool` — True if event matches expected behavior.

### New: `POST /ops/cmdb/{name}/baseline`

Set baseline behavior for a service:
```json
{"expected_restarts_per_day": 2, "expected_events": ["remediation.restart"]}
```

### New: `src/tasks/severity_scorer.py`

`score_severity(target, event_data) -> str` — considers service_type, critical flag,
dependency count from CMDB. Critical + high deps → high. Non-critical utility → low.

### Extend metrics

- `false_positive_rate_by_service_type`: per-service breakdown
- `baseline_coverage`: % of CMDB services with populated baseline_behavior

---

## Issue #6: Operationalize Blind Spot Detection

### New gap patterns in `src/tasks/gap_detection.py`

- `gap:coverage:generic-fallback` — triage diagnosis unknown, confidence < 0.5
- `gap:accuracy:wrong-recommendation` — remediation differs from triage recommendation
- `gap:monitoring:unseen-service` — no events for CMDB service in 7 days
- `gap:security:stale-finding` — security gap unresolved for 30d

### New: `src/tasks/gap_sweep.py`

`run_gap_sweep()` — runs all gap checks. Called on demand or periodically.

### New: `POST /ops/gaps/sweep`

Trigger gap sweep on demand. Returns summary.

### Extend session briefing

`GET /ops/events/context` includes gap summary for CC session start.

---

## Issue #18: CC Governance Rules

Four markdown files in `.claude/rules/`:

- `governance.md` — Top-level Corvus compliance rules
- `tasks/ops-protocol.md` — Operational protocol procedure
- `agents/responder.md` — Responder role with SOP integration
- `agents/changemaker.md` — Changemaker role with event emission

Uses short MCP tool names (ops_check_target, ops_emit_event, etc.).
