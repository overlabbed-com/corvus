# Issue #4: Feedback Loop — Runbook Effectiveness Metrics

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track triage executions and their outcomes so runbook effectiveness is measurable and queryable.

**Architecture:** New `ops_triage_log` table stores every triage execution. The existing `POST /ops/runbooks/triage` endpoint writes a log entry after each execution. New `PATCH /ops/triage/{id}` records outcomes. Metrics router extended with `runbook_hit_rate`, `escalation_rate_by_runbook`, and `avg_resolution_time_by_service_type`.

**Tech Stack:** FastAPI, aiosqlite, pytest (all existing)

**Branch:** `feat/issue-4-feedback-loop`

**QUALITY GATES — ALL MUST PASS BEFORE PUSHING:**
```bash
cd corvus-server
ruff check src/ tests/
ruff format --check src/ tests/
bandit -r src/ -c pyproject.toml
python3 -m pytest tests/ -v --ignore=tests/test_mcp_server.py
```

---

### Task 1: Add ops_triage_log table to schema

**Files:**
- Modify: `corvus-server/src/database.py`
- Modify: `corvus-server/tests/conftest.py` (add table to cleanup)

**Step 1: Add table to schema**

In `corvus-server/src/database.py`, add to the SCHEMA string before the closing `"""`:

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

**Step 2: Add to conftest cleanup**

In `corvus-server/tests/conftest.py`, add `"ops_triage_log"` to the table cleanup list:

```python
        for table in (
            "ops_changes",
            "ops_events",
            "ops_incidents",
            "ops_problems",
            "ops_cmdb",
            "ops_audit_log",
            "ops_triage_log",
        ):
```

**Step 3: Run tests**

Run: `cd corvus-server && python3 -m pytest tests/ -v --ignore=tests/test_mcp_server.py`
Expected: All existing tests PASS (schema addition is backwards-compatible)

**Step 4: Commit**

```bash
git add corvus-server/src/database.py corvus-server/tests/conftest.py
git commit -m "feat(#4): add ops_triage_log table for triage execution tracking"
```

---

### Task 2: Persist triage executions and add triage endpoints

**Files:**
- Modify: `corvus-server/src/routers/runbooks.py`
- Create: `corvus-server/tests/test_triage_feedback.py`

**Step 1: Write the failing tests**

Create `corvus-server/tests/test_triage_feedback.py`:

```python
"""Tests for triage feedback loop (issue #4)."""

import pytest

from tests.conftest import client  # noqa: F401


@pytest.mark.asyncio
async def test_triage_creates_log_entry(client):
    """POST /ops/runbooks/triage should persist a triage log entry."""
    # Register a service in CMDB first
    await client.post("/ops/cmdb/register", json={
        "name": "vllm-primary",
        "host": "host-04",
        "service_type": "inference",
        "critical": True,
    })

    # Run triage
    resp = await client.post("/ops/runbooks/triage", json={
        "target": "vllm-primary",
        "service_type": "inference",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "triage_id" in data

    # Verify log entry exists
    resp = await client.get("/ops/triage")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) >= 1
    assert entries[0]["target"] == "vllm-primary"
    assert entries[0]["service_type"] == "inference"
    assert entries[0]["outcome"] == "pending"


@pytest.mark.asyncio
async def test_triage_outcome_success(client):
    """PATCH /ops/triage/{id} should record outcome."""
    await client.post("/ops/cmdb/register", json={
        "name": "vllm-primary",
        "host": "host-04",
        "service_type": "inference",
        "critical": True,
    })

    resp = await client.post("/ops/runbooks/triage", json={
        "target": "vllm-primary",
        "service_type": "inference",
    })
    triage_id = resp.json()["triage_id"]

    # Record success
    resp = await client.patch(f"/ops/triage/{triage_id}", json={
        "outcome": "success",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "success"
    assert data["resolution_time_minutes"] is not None


@pytest.mark.asyncio
async def test_triage_outcome_failure(client):
    """PATCH /ops/triage/{id} with failure should record correctly."""
    await client.post("/ops/cmdb/register", json={
        "name": "redis-primary",
        "host": "host-04",
        "service_type": "database",
        "critical": True,
    })

    resp = await client.post("/ops/runbooks/triage", json={
        "target": "redis-primary",
        "service_type": "database",
    })
    triage_id = resp.json()["triage_id"]

    resp = await client.patch(f"/ops/triage/{triage_id}", json={
        "outcome": "failure",
    })
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "failure"


@pytest.mark.asyncio
async def test_triage_list_filters(client):
    """GET /ops/triage should support filters."""
    await client.post("/ops/cmdb/register", json={
        "name": "vllm-primary",
        "host": "host-04",
        "service_type": "inference",
        "critical": True,
    })

    await client.post("/ops/runbooks/triage", json={
        "target": "vllm-primary",
        "service_type": "inference",
    })

    # Filter by service_type
    resp = await client.get("/ops/triage", params={"service_type": "inference"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Filter by nonexistent service_type
    resp = await client.get("/ops/triage", params={"service_type": "nonexistent"})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_triage_no_runbook_still_logs(client):
    """Triage with no matching runbook should still create a log entry."""
    await client.post("/ops/cmdb/register", json={
        "name": "custom-svc",
        "host": "host-04",
        "service_type": "custom_type",
    })

    resp = await client.post("/ops/runbooks/triage", json={
        "target": "custom-svc",
        "service_type": "custom_type",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "no_runbook"
    # Should still have triage_id for tracking
    assert "triage_id" in data
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python3 -m pytest tests/test_triage_feedback.py -v`
Expected: FAIL — `triage_id` not in response, `/ops/triage` returns 404

**Step 3: Modify the runbooks router**

In `corvus-server/src/routers/runbooks.py`, add the triage persistence and new endpoints. The key changes:

1. Import `uuid`, `datetime`, `get_db`, `Query`
2. After `execute_triage()` returns, write a row to `ops_triage_log`
3. Add `triage_id` to the response
4. Add `GET /ops/triage` (list with filters)
5. Add `PATCH /ops/triage/{triage_id}` (record outcome)
6. For the `no_runbook` case, also write a triage log entry

Add new model:

```python
class TriageOutcome(BaseModel):
    outcome: str  # "success" or "failure"
    related_incident_id: str | None = None
```

The triage persistence in `run_triage`:

```python
import uuid
from datetime import UTC, datetime
from fastapi import Query as FastQuery
from src.database import get_db

# After triage execution (both success and no_runbook paths):
triage_id = f"TRG-{uuid.uuid4().hex[:8].upper()}"
now = datetime.now(UTC).isoformat()
action_type = f"{result.diagnosis or 'unknown'}:{service_type}"

db = await get_db()
try:
    await db.execute(
        """INSERT INTO ops_triage_log
           (id, timestamp, target, service_type, runbook_name, action_type,
            diagnosis, confidence, escalation_required, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (triage_id, now, request.target, service_type, runbook.name,
         action_type, result.diagnosis, result.confidence,
         1 if result.escalation_required else 0),
    )
    await db.commit()
finally:
    await db.close()

# Include triage_id in response
return {
    "status": "triaged",
    "triage_id": triage_id,
    "target": request.target,
    "service_type": service_type,
    **result.to_dict(),
}
```

New endpoints:

```python
@router.get("/ops/triage")
async def list_triage(
    service_type: str | None = FastQuery(None),
    runbook_name: str | None = FastQuery(None),
    outcome: str | None = FastQuery(None),
    limit: int = FastQuery(100, le=1000),
):
    """List triage log entries with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_triage_log WHERE 1=1"
        params: list = []
        if service_type:
            query += " AND service_type = ?"
            params.append(service_type)
        if runbook_name:
            query += " AND runbook_name = ?"
            params.append(runbook_name)
        if outcome:
            query += " AND outcome = ?"
            params.append(outcome)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.patch("/ops/triage/{triage_id}")
async def record_triage_outcome(triage_id: str, outcome_req: TriageOutcome):
    """Record the outcome of a triage execution."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ops_triage_log WHERE id = ?", (triage_id,)
        )
        entry = await cursor.fetchone()
        if not entry:
            raise HTTPException(status_code=404, detail="Triage entry not found")

        now = datetime.now(UTC)
        created = datetime.fromisoformat(entry["timestamp"])
        minutes = int((now - created).total_seconds() / 60)

        sets = ["outcome = ?", "outcome_at = ?", "resolution_time_minutes = ?"]
        params = [outcome_req.outcome, now.isoformat(), minutes]

        if outcome_req.related_incident_id:
            sets.append("related_incident_id = ?")
            params.append(outcome_req.related_incident_id)

        params.append(triage_id)
        await db.execute(
            f"UPDATE ops_triage_log SET {', '.join(sets)} WHERE id = ?",  # nosec B608 # nosemgrep
            params,
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM ops_triage_log WHERE id = ?", (triage_id,)
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()
```

**Note:** The `GET /ops/triage` and `PATCH /ops/triage/{triage_id}` routes are on the runbooks router which has prefix `/ops/runbooks`. These new routes need a separate prefix. Either add them to a new router or use the `router` without prefix. The simplest approach: add them directly to the runbooks router but with full paths (not using the prefix).

Actually, create a separate triage section in the runbooks file using a second router:

```python
triage_router = APIRouter(tags=["triage"])
# ... GET /ops/triage and PATCH /ops/triage/{triage_id} on triage_router
```

Then register `triage_router` in `app.py`.

**Step 4: Register triage router in app.py**

Add to `corvus-server/src/app.py`:

```python
from src.routers.runbooks import triage_router
# ...
app.include_router(triage_router)
```

**Step 5: Run tests**

Run: `cd corvus-server && python3 -m pytest tests/test_triage_feedback.py -v`
Expected: All PASS

**Step 6: Run full test suite**

Run: `cd corvus-server && python3 -m pytest tests/ -v --ignore=tests/test_mcp_server.py`
Expected: All PASS

**Step 7: Commit**

```bash
git add corvus-server/src/routers/runbooks.py corvus-server/src/app.py corvus-server/tests/test_triage_feedback.py
git commit -m "feat(#4): persist triage executions and add outcome recording"
```

---

### Task 3: Add triage effectiveness metrics

**Files:**
- Modify: `corvus-server/src/routers/metrics.py`
- Add to: `corvus-server/tests/test_triage_feedback.py`

**Step 1: Write the failing tests**

Add to `corvus-server/tests/test_triage_feedback.py`:

```python
@pytest.mark.asyncio
async def test_metrics_include_triage_stats(client):
    """GET /ops/metrics should include triage effectiveness stats."""
    resp = await client.get("/ops/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "runbook_hit_rate" in data
    assert "escalation_rate_by_runbook" in data
    assert "avg_resolution_time_by_service_type" in data


@pytest.mark.asyncio
async def test_metrics_runbook_hit_rate(client):
    """Runbook hit rate should reflect diagnosis confidence."""
    await client.post("/ops/cmdb/register", json={
        "name": "vllm-primary",
        "host": "host-04",
        "service_type": "inference",
        "critical": True,
    })

    # Run triage (will produce a result with some confidence)
    await client.post("/ops/runbooks/triage", json={
        "target": "vllm-primary",
        "service_type": "inference",
    })

    resp = await client.get("/ops/metrics")
    data = resp.json()
    # Should have a numeric hit rate
    assert isinstance(data["runbook_hit_rate"], (int, float))
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python3 -m pytest tests/test_triage_feedback.py::test_metrics_include_triage_stats -v`
Expected: FAIL — keys not in metrics response

**Step 3: Add triage stats to metrics router**

In `corvus-server/src/routers/metrics.py`, add before the `return metrics` line in `get_metrics()`:

```python
# Triage effectiveness (from ops_triage_log)
cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_triage_log")
row = await cursor.fetchone()
total_triages = row["cnt"]

if total_triages > 0:
    # Hit rate: % of triages with confidence > 0.5
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE confidence > 0.5"
    )
    row = await cursor.fetchone()
    metrics["runbook_hit_rate"] = round(row["cnt"] / total_triages * 100, 1)
else:
    metrics["runbook_hit_rate"] = 0.0

# Escalation rate by runbook
cursor = await db.execute(
    """SELECT runbook_name,
              COUNT(*) as total,
              SUM(escalation_required) as escalated
       FROM ops_triage_log
       GROUP BY runbook_name"""
)
rows = await cursor.fetchall()
metrics["escalation_rate_by_runbook"] = {
    r["runbook_name"]: round(r["escalated"] / r["total"] * 100, 1)
    for r in rows if r["total"] > 0
}

# Avg resolution time by service_type (only resolved triages)
cursor = await db.execute(
    """SELECT service_type,
              AVG(resolution_time_minutes) as avg_time
       FROM ops_triage_log
       WHERE outcome IN ('success', 'failure')
         AND resolution_time_minutes IS NOT NULL
       GROUP BY service_type"""
)
rows = await cursor.fetchall()
metrics["avg_resolution_time_by_service_type"] = {
    r["service_type"]: round(r["avg_time"], 1) for r in rows
}
```

**Step 4: Run tests**

Run: `cd corvus-server && python3 -m pytest tests/test_triage_feedback.py -v`
Expected: All PASS

**Step 5: Run full test suite + quality gates**

```bash
cd corvus-server
ruff check src/ tests/
ruff format --check src/ tests/
bandit -r src/ -c pyproject.toml
python3 -m pytest tests/ -v --ignore=tests/test_mcp_server.py
```
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus-server/src/routers/metrics.py corvus-server/tests/test_triage_feedback.py
git commit -m "feat(#4): add runbook_hit_rate, escalation_rate, resolution_time to metrics"
```

---

### Task 4: Final — quality gates and PR

**Step 1: Run all quality gates**

```bash
cd corvus-server
ruff check src/ tests/
ruff format --check src/ tests/
bandit -r src/ -c pyproject.toml
python3 -m pytest tests/ -v --ignore=tests/test_mcp_server.py
```
Expected: All PASS. If any gate fails, fix before pushing.

**Step 2: Push and create PR**

```bash
git push -u origin feat/issue-4-feedback-loop
gh pr create --title "feat: feedback loop — runbook effectiveness metrics (#4)" \
  --body "$(cat <<'EOF'
## Summary
- New `ops_triage_log` table persists every triage execution
- `POST /ops/runbooks/triage` now writes a log entry with `triage_id` in response
- `PATCH /ops/triage/{id}` records outcome (success/failure) with resolution time
- `GET /ops/triage` lists triage log with filters
- `GET /ops/metrics` extended with `runbook_hit_rate`, `escalation_rate_by_runbook`, `avg_resolution_time_by_service_type`

Closes #4

## Test plan
- [ ] `pytest tests/test_triage_feedback.py -v` — all triage tests pass
- [ ] `pytest tests/ -v` — full suite, no regressions
- [ ] `ruff check src/ tests/` — clean
- [ ] `bandit -r src/ -c pyproject.toml` — clean
EOF
)"
```
