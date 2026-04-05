# NEXT Sprint Design — Issues #4, #8

> Approved: 2026-03-29
> Issues: #4 (Feedback Loop — Runbook Effectiveness), #8 (Trust Ledger)
> Parallel execution: 2 independent branches (shared schema addition on main first)

---

## Shared: `ops_triage_log` table

Both issues depend on persisting triage executions. Add to `database.py`:

```sql
CREATE TABLE IF NOT EXISTS ops_triage_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    target TEXT NOT NULL,
    service_type TEXT NOT NULL,
    runbook_name TEXT NOT NULL,
    action_type TEXT NOT NULL,
    diagnosis TEXT,
    confidence REAL,
    escalation_required INTEGER DEFAULT 0,
    outcome TEXT DEFAULT 'pending',
    outcome_at TEXT,
    related_incident_id TEXT,
    resolution_time_minutes INTEGER
);

CREATE INDEX IF NOT EXISTS idx_triage_log_action_type ON ops_triage_log(action_type);
CREATE INDEX IF NOT EXISTS idx_triage_log_service_type ON ops_triage_log(service_type);
CREATE INDEX IF NOT EXISTS idx_triage_log_outcome ON ops_triage_log(outcome);
```

---

## Issue #4: Feedback Loop — Runbook Effectiveness Metrics

### Changes to `POST /ops/runbooks/triage`

After executing triage, write a row to `ops_triage_log`:
- `action_type` = `{remediation_type}:{service_type}` (e.g., `remediation.restart:inference`)
- `diagnosis`, `confidence`, `escalation_required` from TriageResult
- `outcome` = `"pending"` (updated later via PATCH)

### New: `PATCH /ops/triage/{triage_id}`

Records the outcome after the agent acts:
- Accepts `outcome: "success" | "failure"`
- Calculates `resolution_time_minutes` from triage timestamp to now
- Triggers trust ledger update (issue #8)

### New: `GET /ops/triage`

List triage log with filters: `service_type`, `runbook_name`, `outcome`, `since`.

### Extend `GET /ops/metrics`

- `runbook_hit_rate`: % of triages with confidence > 0.5
- `escalation_rate_by_runbook`: { runbook_name: escalation % }
- `avg_resolution_time_by_service_type`: { service_type: avg minutes }

### Files to create/modify

- Modify: `src/database.py` (add ops_triage_log table)
- Modify: `src/routers/runbooks.py` (persist triage, add PATCH/GET endpoints)
- Modify: `src/routers/metrics.py` (add triage effectiveness stats)
- Tests: `tests/test_triage_feedback.py`

---

## Issue #8: Trust Ledger

### New: `ops_trust_ledger` table

```sql
CREATE TABLE IF NOT EXISTS ops_trust_ledger (
    action_type TEXT PRIMARY KEY,
    total_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    trust_tier TEXT DEFAULT 'ESCALATE',
    promoted_at TEXT,
    demoted_at TEXT
);
```

### New: `src/tasks/trust_ledger.py`

Core logic:
- `record_outcome(action_type, outcome)` — increment counters, evaluate promotion/demotion
- **Promote**: success_rate >= 0.95 AND total_count >= 20 → advance tier (ESCALATE → SUPERVISED → AUTO)
- **Demote**: failure when at AUTO → back to SUPERVISED
- Called from `PATCH /ops/triage/{id}` (issue #4)

### New: `src/routers/trust.py`

- `GET /ops/trust` — full trust ledger (all action types with tiers and stats)
- `GET /ops/trust/{action_type}` — single action type detail

### Integration points

- Target status API (`GET /ops/events/targets/{target}/status`): include trust tier for the target's service type
- Gap detection: action type at ESCALATE for 30d with 0 executions → `gap:autonomy:stuck-escalation`

### Extend `GET /ops/metrics`

- `trust_tiers`: { "ESCALATE": N, "SUPERVISED": N, "AUTO": N }
- `recent_promotions`: action types promoted in last 7d

### Files to create/modify

- Modify: `src/database.py` (add ops_trust_ledger table)
- Create: `src/tasks/trust_ledger.py`
- Create: `src/routers/trust.py`
- Modify: `src/routers/events.py` (trust tier in target status)
- Modify: `src/routers/metrics.py` (trust tier stats)
- Modify: `src/tasks/gap_detection.py` (stuck-escalation gap)
- Modify: `src/app.py` (register trust router)
- Tests: `tests/test_trust_ledger.py`

---

## Independence Check

| | #4 Feedback Loop | #8 Trust Ledger |
|---|---|---|
| **Shared dependency** | `ops_triage_log` table | `ops_triage_log` table |
| **Own tables** | none | `ops_trust_ledger` |
| **Own routes** | PATCH/GET /ops/triage | GET /ops/trust |
| **Metrics** | runbook_hit_rate, escalation_rate, resolution_time | trust_tiers, recent_promotions |

Both need `ops_triage_log`. Strategy: add both tables to `database.py` on main before branching.
The trust ledger's `record_outcome` is called from #4's PATCH endpoint — #4 can stub this call,
and #8 implements the real logic. Integration happens when both merge.
