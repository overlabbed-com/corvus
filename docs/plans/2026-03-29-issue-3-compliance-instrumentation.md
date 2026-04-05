# Issue #3: Compliance Instrumentation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add compliance metrics to `GET /ops/metrics` and a detailed compliance audit endpoint at `GET /ops/metrics/compliance`, measuring whether changes and incidents have corresponding events. Target: >90% compliance rate.

**Architecture:** New `src/tasks/compliance_audit.py` module with query logic. Extended metrics router with compliance stats summary and detailed audit endpoint. Uses existing gap detection to auto-flag compliance gaps as problem records.

**Tech Stack:** FastAPI, aiosqlite, pytest (all existing)

**Branch:** `feat/issue-3-compliance-instrumentation`

---

### Task 1: Add compliance stats to GET /ops/metrics

**Files:**
- Modify: `corvus-server/src/routers/metrics.py`
- Create: `corvus-server/tests/test_compliance.py`

**Step 1: Write the failing tests**

Create `corvus-server/tests/test_compliance.py`:

```python
"""Tests for compliance instrumentation (issue #3)."""

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import client  # noqa: F401


@pytest.mark.asyncio
async def test_metrics_include_compliance(client):
    """GET /ops/metrics should include compliance stats."""
    resp = await client.get("/ops/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "compliance_rate" in data
    assert "event_emission_gap_count" in data
    assert "uncovered_event_types" in data


@pytest.mark.asyncio
async def test_compliance_rate_with_no_data(client):
    """Compliance rate should be 100.0 when there are no changes."""
    resp = await client.get("/ops/metrics")
    data = resp.json()
    # No changes = no gaps = 100% compliant (vacuously true)
    assert data["compliance_rate"] == 100.0
    assert data["event_emission_gap_count"] == 0


@pytest.mark.asyncio
async def test_compliance_rate_with_covered_change(client):
    """A change with a matching event should count as covered."""
    # Create a change
    change_resp = await client.post("/ops/changes", json={
        "targets": ["vllm-primary"],
        "description": "deploy update",
        "created_by": "test-agent",
    })
    change_id = change_resp.json()["id"]

    # Emit a matching event
    await client.post("/ops/events", json={
        "source": "test-agent",
        "type": "change.started",
        "target": "vllm-primary",
        "related_change_id": change_id,
    })

    resp = await client.get("/ops/metrics")
    data = resp.json()
    assert data["compliance_rate"] == 100.0
    assert data["event_emission_gap_count"] == 0


@pytest.mark.asyncio
async def test_compliance_rate_with_uncovered_change(client):
    """A change without a matching event should be flagged as a gap."""
    # Create a change with no corresponding event
    await client.post("/ops/changes", json={
        "targets": ["vllm-primary"],
        "description": "silent change",
        "created_by": "test-agent",
    })

    resp = await client.get("/ops/metrics")
    data = resp.json()
    assert data["compliance_rate"] == 0.0
    assert data["event_emission_gap_count"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python -m pytest tests/test_compliance.py -v`
Expected: FAIL — `compliance_rate` not in response

**Step 3: Add compliance stats to metrics router**

In `corvus-server/src/routers/metrics.py`, add compliance queries before the `return metrics` statement:

```python
# Compliance: changes with corresponding events
cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_changes")
row = await cursor.fetchone()
total_changes = row["cnt"]

if total_changes > 0:
    # A change is "covered" if any event references it via related_change_id
    cursor = await db.execute(
        """SELECT COUNT(DISTINCT c.id) as cnt
           FROM ops_changes c
           INNER JOIN ops_events e ON e.related_change_id = c.id"""
    )
    row = await cursor.fetchone()
    covered_changes = row["cnt"]
    metrics["compliance_rate"] = round(
        covered_changes / total_changes * 100, 1
    )
    metrics["event_emission_gap_count"] = total_changes - covered_changes
else:
    metrics["compliance_rate"] = 100.0
    metrics["event_emission_gap_count"] = 0

# Uncovered event types: known types with zero occurrences in last 24h
known_types = [
    "change.started", "change.completed", "change.failed",
    "incident.opened", "incident.investigating", "incident.resolved",
    "remediation.restart", "remediation.config_fix",
    "sweep.completed", "sweep.anomaly",
    "session.started", "session.ended",
]
cursor = await db.execute(
    "SELECT DISTINCT type FROM ops_events WHERE timestamp >= ?",
    (last_24h,),
)
rows = await cursor.fetchall()
seen_types = {r["type"] for r in rows}
metrics["uncovered_event_types"] = sorted(
    t for t in known_types if t not in seen_types
)
```

**Step 4: Run tests to verify they pass**

Run: `cd corvus-server && python -m pytest tests/test_compliance.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus-server/src/routers/metrics.py corvus-server/tests/test_compliance.py
git commit -m "feat(#3): add compliance_rate, gap_count, uncovered_types to /ops/metrics"
```

---

### Task 2: Build detailed compliance audit endpoint

**Files:**
- Create: `corvus-server/src/tasks/compliance_audit.py`
- Modify: `corvus-server/src/routers/metrics.py`
- Add to: `corvus-server/tests/test_compliance.py`

**Step 1: Write the failing tests**

Add to `corvus-server/tests/test_compliance.py`:

```python
@pytest.mark.asyncio
async def test_compliance_audit_endpoint(client):
    """GET /ops/metrics/compliance should return detailed breakdown."""
    resp = await client.get("/ops/metrics/compliance")
    assert resp.status_code == 200
    data = resp.json()
    assert "compliance_rate" in data
    assert "changes" in data
    assert "incidents" in data
    assert "by_source" in data


@pytest.mark.asyncio
async def test_compliance_audit_change_detail(client):
    """Compliance audit should list uncovered changes."""
    # Create an uncovered change
    change_resp = await client.post("/ops/changes", json={
        "targets": ["redis-primary"],
        "description": "uncovered change",
        "created_by": "test-agent",
    })
    change_id = change_resp.json()["id"]

    resp = await client.get("/ops/metrics/compliance")
    data = resp.json()
    uncovered = data["changes"]["uncovered"]
    assert any(c["id"] == change_id for c in uncovered)


@pytest.mark.asyncio
async def test_compliance_audit_by_source(client):
    """Compliance audit should break down by source."""
    # Create a change and event from a specific source
    change_resp = await client.post("/ops/changes", json={
        "targets": ["vllm-primary"],
        "description": "sourced change",
        "created_by": "claude-code",
    })
    change_id = change_resp.json()["id"]

    await client.post("/ops/events", json={
        "source": "claude-code",
        "type": "change.started",
        "target": "vllm-primary",
        "related_change_id": change_id,
    })

    resp = await client.get("/ops/metrics/compliance")
    data = resp.json()
    assert "claude-code" in data["by_source"]


@pytest.mark.asyncio
async def test_compliance_audit_incidents(client):
    """Compliance audit should include incident coverage."""
    # Create an incident
    inc_resp = await client.post("/ops/incidents", json={
        "target": "vllm-primary",
        "title": "test incident",
        "detected_by": "nemoclaw",
    })
    inc_id = inc_resp.json()["id"]

    # Emit a matching event
    await client.post("/ops/events", json={
        "source": "nemoclaw",
        "type": "incident.opened",
        "target": "vllm-primary",
        "related_incident_id": inc_id,
    })

    resp = await client.get("/ops/metrics/compliance")
    data = resp.json()
    assert data["incidents"]["total"] >= 1
    assert data["incidents"]["covered"] >= 1
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python -m pytest tests/test_compliance.py::test_compliance_audit_endpoint -v`
Expected: FAIL — 404 or 405 (endpoint doesn't exist)

**Step 3: Create compliance audit module**

Create `corvus-server/src/tasks/compliance_audit.py`:

```python
"""Compliance audit — measures event coverage for changes and incidents.

Issue #3: >90% of changes/incidents should have corresponding events.
"""

from typing import Any

import aiosqlite


async def run_compliance_audit(db: aiosqlite.Connection) -> dict[str, Any]:
    """Run a full compliance audit and return detailed breakdown.

    Checks:
    - Changes with corresponding events (via related_change_id)
    - Incidents with corresponding events (via related_incident_id)
    - Breakdown by source/created_by
    """
    result: dict[str, Any] = {}

    # --- Change compliance ---
    cursor = await db.execute(
        "SELECT id, created_by, description, targets, created_at FROM ops_changes"
    )
    all_changes = await cursor.fetchall()

    cursor = await db.execute(
        "SELECT DISTINCT related_change_id FROM ops_events WHERE related_change_id IS NOT NULL"
    )
    covered_change_ids = {row["related_change_id"] for row in await cursor.fetchall()}

    uncovered_changes = [
        {"id": c["id"], "created_by": c["created_by"], "description": c["description"]}
        for c in all_changes if c["id"] not in covered_change_ids
    ]

    total_changes = len(all_changes)
    covered_count = total_changes - len(uncovered_changes)

    result["changes"] = {
        "total": total_changes,
        "covered": covered_count,
        "uncovered": uncovered_changes,
    }

    # --- Incident compliance ---
    cursor = await db.execute(
        "SELECT id, detected_by, title, target, created_at FROM ops_incidents"
    )
    all_incidents = await cursor.fetchall()

    cursor = await db.execute(
        "SELECT DISTINCT related_incident_id FROM ops_events WHERE related_incident_id IS NOT NULL"
    )
    covered_incident_ids = {row["related_incident_id"] for row in await cursor.fetchall()}

    uncovered_incidents = [
        {"id": i["id"], "detected_by": i["detected_by"], "title": i["title"]}
        for i in all_incidents if i["id"] not in covered_incident_ids
    ]

    total_incidents = len(all_incidents)
    covered_incidents = total_incidents - len(uncovered_incidents)

    result["incidents"] = {
        "total": total_incidents,
        "covered": covered_incidents,
        "uncovered": uncovered_incidents,
    }

    # --- Overall compliance rate ---
    total = total_changes + total_incidents
    covered = covered_count + covered_incidents
    result["compliance_rate"] = round(covered / total * 100, 1) if total > 0 else 100.0

    # --- Breakdown by source ---
    by_source: dict[str, dict[str, int]] = {}

    for c in all_changes:
        src = c["created_by"] or "unknown"
        if src not in by_source:
            by_source[src] = {"changes_total": 0, "changes_covered": 0,
                              "incidents_total": 0, "incidents_covered": 0}
        by_source[src]["changes_total"] += 1
        if c["id"] in covered_change_ids:
            by_source[src]["changes_covered"] += 1

    for i in all_incidents:
        src = i["detected_by"] or "unknown"
        if src not in by_source:
            by_source[src] = {"changes_total": 0, "changes_covered": 0,
                              "incidents_total": 0, "incidents_covered": 0}
        by_source[src]["incidents_total"] += 1
        if i["id"] in covered_incident_ids:
            by_source[src]["incidents_covered"] += 1

    result["by_source"] = by_source

    return result
```

**Step 4: Add the compliance audit endpoint to the metrics router**

In `corvus-server/src/routers/metrics.py`, add:

```python
from src.tasks.compliance_audit import run_compliance_audit

@router.get("/ops/metrics/compliance")
async def compliance_audit():
    """Detailed compliance audit — per-change, per-incident coverage."""
    db = await get_db()
    try:
        return await run_compliance_audit(db)
    finally:
        await db.close()
```

**Important:** This new route MUST be defined BEFORE the existing `/ops/metrics` route in the file, or use a separate prefix. Since both share the same router and `/ops/metrics/compliance` is more specific than `/ops/metrics`, FastAPI will match correctly as long as `compliance` route is registered first.

**Step 5: Run tests**

Run: `cd corvus-server && python -m pytest tests/test_compliance.py -v`
Expected: All PASS

**Step 6: Run full test suite**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add corvus-server/src/tasks/compliance_audit.py corvus-server/src/routers/metrics.py corvus-server/tests/test_compliance.py
git commit -m "feat(#3): add /ops/metrics/compliance detailed audit endpoint"
```

---

### Task 3: Final — run full test suite and push

**Step 1: Run full test suite**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 2: Push branch and create PR**

```bash
git push -u origin feat/issue-3-compliance-instrumentation
gh pr create --title "feat: compliance instrumentation — >90% event coverage metrics (#3)" \
  --body "$(cat <<'EOF'
## Summary
- Extended `GET /ops/metrics` with `compliance_rate`, `event_emission_gap_count`, `uncovered_event_types`
- New `GET /ops/metrics/compliance` endpoint with detailed per-change, per-incident, per-source breakdown
- Compliance measured by: changes/incidents with corresponding events (via related_change_id/related_incident_id)

Closes #3

## Test plan
- [ ] `pytest tests/test_compliance.py -v` — all compliance tests pass
- [ ] `pytest tests/ -v` — full suite passes with no regressions
- [ ] Verify compliance_rate is 100.0 with no data (vacuously true)
- [ ] Verify uncovered changes appear in audit detail
EOF
)"
```
