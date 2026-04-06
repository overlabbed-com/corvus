# Issue #8: Trust Ledger — Action-Type Tracking + Auto-Promotion

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track success/failure rates of agent action types and automatically promote high-confidence actions through trust tiers (ESCALATE → SUPERVISED → AUTO).

**Architecture:** New `ops_trust_ledger` table with per-action-type counters and trust tiers. Core logic in `src/tasks/trust_ledger.py` handles promotion (>95% success over 20+ executions) and demotion (any failure at AUTO). New trust router exposes the ledger. Integrated into target status API and gap detection.

**Tech Stack:** FastAPI, aiosqlite, pytest (all existing)

**Branch:** `feat/issue-8-trust-ledger`

**QUALITY GATES — ALL MUST PASS BEFORE PUSHING:**
```bash
cd corvus-server
ruff check src/ tests/
ruff format --check src/ tests/
bandit -r src/ -c pyproject.toml
python3 -m pytest tests/ -v --ignore=tests/test_mcp_server.py
```

---

### Task 1: Add ops_trust_ledger table to schema

**Files:**
- Modify: `corvus-server/src/database.py`
- Modify: `corvus-server/tests/conftest.py`

**Step 1: Add table to schema**

In `corvus-server/src/database.py`, add to the SCHEMA string (after `ops_triage_log` if it already exists from #4, otherwise before the closing `"""`):

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

Also add `ops_triage_log` if not already present (both issues share it):

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

In `corvus-server/tests/conftest.py`, add `"ops_trust_ledger"` and `"ops_triage_log"` to the table cleanup list.

**Step 3: Run tests**

Run: `cd corvus-server && python3 -m pytest tests/ -v --ignore=tests/test_mcp_server.py`
Expected: All existing tests PASS

**Step 4: Commit**

```bash
git add corvus-server/src/database.py corvus-server/tests/conftest.py
git commit -m "feat(#8): add ops_trust_ledger and ops_triage_log tables"
```

---

### Task 2: Build trust ledger core logic

**Files:**
- Create: `corvus-server/src/tasks/trust_ledger.py`
- Create: `corvus-server/tests/test_trust_ledger.py`

**Step 1: Write the failing tests**

Create `corvus-server/tests/test_trust_ledger.py`:

```python
"""Tests for trust ledger (issue #8)."""

import pytest

from src.database import get_db, init_db
from src.tasks.trust_ledger import record_outcome, get_trust_tier, TIER_ESCALATE, TIER_SUPERVISED, TIER_AUTO


@pytest.fixture
async def db():
    """Get a fresh database connection."""
    await init_db()
    conn = await get_db()
    try:
        await conn.execute("DELETE FROM ops_trust_ledger")
        await conn.commit()
        yield conn
    finally:
        await conn.close()


class TestRecordOutcome:

    @pytest.mark.asyncio
    async def test_first_success_creates_entry(self, db):
        """First outcome for an action type should create a ledger entry."""
        await record_outcome("remediation.restart:inference", "success")
        tier = await get_trust_tier("remediation.restart:inference")
        assert tier["total_count"] == 1
        assert tier["success_count"] == 1
        assert tier["trust_tier"] == TIER_ESCALATE

    @pytest.mark.asyncio
    async def test_failure_increments(self, db):
        """Failure should increment failure_count."""
        await record_outcome("remediation.restart:inference", "failure")
        tier = await get_trust_tier("remediation.restart:inference")
        assert tier["failure_count"] == 1
        assert tier["total_count"] == 1

    @pytest.mark.asyncio
    async def test_multiple_outcomes_accumulate(self, db):
        """Multiple outcomes should accumulate correctly."""
        for _ in range(5):
            await record_outcome("remediation.restart:inference", "success")
        await record_outcome("remediation.restart:inference", "failure")
        tier = await get_trust_tier("remediation.restart:inference")
        assert tier["total_count"] == 6
        assert tier["success_count"] == 5
        assert tier["failure_count"] == 1


class TestPromotion:

    @pytest.mark.asyncio
    async def test_promote_after_20_successes(self, db):
        """Should promote from ESCALATE to SUPERVISED after 20+ successes at >95%."""
        for _ in range(20):
            await record_outcome("restart:db", "success")
        tier = await get_trust_tier("restart:db")
        assert tier["trust_tier"] == TIER_SUPERVISED
        assert tier["promoted_at"] is not None

    @pytest.mark.asyncio
    async def test_promote_to_auto(self, db):
        """Should promote from SUPERVISED to AUTO after another 20 successes."""
        # First 20 → SUPERVISED
        for _ in range(20):
            await record_outcome("restart:proxy", "success")
        # Next 20 → AUTO (total 40, still >95%)
        for _ in range(20):
            await record_outcome("restart:proxy", "success")
        tier = await get_trust_tier("restart:proxy")
        assert tier["trust_tier"] == TIER_AUTO

    @pytest.mark.asyncio
    async def test_no_promote_below_threshold(self, db):
        """Should NOT promote if success rate < 95%."""
        for _ in range(18):
            await record_outcome("restart:media", "success")
        for _ in range(2):
            await record_outcome("restart:media", "failure")
        tier = await get_trust_tier("restart:media")
        # 90% success rate — not enough
        assert tier["trust_tier"] == TIER_ESCALATE

    @pytest.mark.asyncio
    async def test_no_promote_below_count(self, db):
        """Should NOT promote with fewer than 20 executions."""
        for _ in range(19):
            await record_outcome("restart:dns", "success")
        tier = await get_trust_tier("restart:dns")
        assert tier["trust_tier"] == TIER_ESCALATE


class TestDemotion:

    @pytest.mark.asyncio
    async def test_demote_auto_on_failure(self, db):
        """Any failure at AUTO should demote to SUPERVISED."""
        # Promote to AUTO
        for _ in range(40):
            await record_outcome("restart:util", "success")
        tier = await get_trust_tier("restart:util")
        assert tier["trust_tier"] == TIER_AUTO

        # One failure → demote
        await record_outcome("restart:util", "failure")
        tier = await get_trust_tier("restart:util")
        assert tier["trust_tier"] == TIER_SUPERVISED
        assert tier["demoted_at"] is not None

    @pytest.mark.asyncio
    async def test_no_demote_supervised_on_failure(self, db):
        """Failure at SUPERVISED should NOT demote further."""
        for _ in range(20):
            await record_outcome("restart:iot", "success")
        tier = await get_trust_tier("restart:iot")
        assert tier["trust_tier"] == TIER_SUPERVISED

        await record_outcome("restart:iot", "failure")
        tier = await get_trust_tier("restart:iot")
        # Stays SUPERVISED, not demoted to ESCALATE
        assert tier["trust_tier"] == TIER_SUPERVISED


class TestGetTrustTier:

    @pytest.mark.asyncio
    async def test_unknown_action_type(self, db):
        """Unknown action type should return ESCALATE with zero counts."""
        tier = await get_trust_tier("nonexistent:type")
        assert tier["trust_tier"] == TIER_ESCALATE
        assert tier["total_count"] == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python3 -m pytest tests/test_trust_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tasks.trust_ledger'`

**Step 3: Create the trust ledger module**

Create `corvus-server/src/tasks/trust_ledger.py`:

```python
"""Trust ledger — tracks action-type success rates and manages trust tiers.

Agents earn trust through demonstrated competence:
  ESCALATE → SUPERVISED → AUTO

Promotion: >95% success rate over 20+ executions → advance one tier.
Demotion: Any failure at AUTO → back to SUPERVISED.
"""

from datetime import UTC, datetime
from typing import Any

from src.database import get_db

TIER_ESCALATE = "ESCALATE"
TIER_SUPERVISED = "SUPERVISED"
TIER_AUTO = "AUTO"

TIER_ORDER = [TIER_ESCALATE, TIER_SUPERVISED, TIER_AUTO]

PROMOTION_THRESHOLD = 0.95  # 95% success rate
PROMOTION_MIN_COUNT = 20    # minimum executions before promotion


async def record_outcome(action_type: str, outcome: str) -> dict[str, Any]:
    """Record a triage outcome and evaluate promotion/demotion.

    Args:
        action_type: e.g., "remediation.restart:inference"
        outcome: "success" or "failure"

    Returns:
        Updated trust ledger entry.
    """
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()

        # Upsert: create entry if not exists
        cursor = await db.execute(
            "SELECT * FROM ops_trust_ledger WHERE action_type = ?",
            (action_type,),
        )
        entry = await cursor.fetchone()

        if not entry:
            await db.execute(
                """INSERT INTO ops_trust_ledger
                   (action_type, total_count, success_count, failure_count, trust_tier)
                   VALUES (?, 0, 0, 0, ?)""",
                (action_type, TIER_ESCALATE),
            )

        # Increment counters
        if outcome == "success":
            await db.execute(
                """UPDATE ops_trust_ledger
                   SET total_count = total_count + 1,
                       success_count = success_count + 1
                   WHERE action_type = ?""",
                (action_type,),
            )
        else:
            await db.execute(
                """UPDATE ops_trust_ledger
                   SET total_count = total_count + 1,
                       failure_count = failure_count + 1
                   WHERE action_type = ?""",
                (action_type,),
            )

        # Re-read current state
        cursor = await db.execute(
            "SELECT * FROM ops_trust_ledger WHERE action_type = ?",
            (action_type,),
        )
        current = await cursor.fetchone()
        current_tier = current["trust_tier"]
        total = current["total_count"]
        successes = current["success_count"]

        # Evaluate demotion first (takes priority)
        if current_tier == TIER_AUTO and outcome == "failure":
            await db.execute(
                "UPDATE ops_trust_ledger SET trust_tier = ?, demoted_at = ? WHERE action_type = ?",
                (TIER_SUPERVISED, now, action_type),
            )
        # Evaluate promotion
        elif total >= PROMOTION_MIN_COUNT:
            success_rate = successes / total
            if success_rate >= PROMOTION_THRESHOLD:
                tier_idx = TIER_ORDER.index(current_tier)
                if tier_idx < len(TIER_ORDER) - 1:
                    new_tier = TIER_ORDER[tier_idx + 1]
                    await db.execute(
                        "UPDATE ops_trust_ledger SET trust_tier = ?, promoted_at = ? "
                        "WHERE action_type = ?",
                        (new_tier, now, action_type),
                    )

        await db.commit()

        # Return final state
        cursor = await db.execute(
            "SELECT * FROM ops_trust_ledger WHERE action_type = ?",
            (action_type,),
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


async def get_trust_tier(action_type: str) -> dict[str, Any]:
    """Get the trust tier for an action type.

    Returns a dict with tier info, or defaults for unknown action types.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ops_trust_ledger WHERE action_type = ?",
            (action_type,),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return {
            "action_type": action_type,
            "total_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "trust_tier": TIER_ESCALATE,
            "promoted_at": None,
            "demoted_at": None,
        }
    finally:
        await db.close()


async def get_all_tiers() -> list[dict[str, Any]]:
    """Get the full trust ledger."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ops_trust_ledger ORDER BY trust_tier, action_type"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
```

**Step 4: Run tests**

Run: `cd corvus-server && python3 -m pytest tests/test_trust_ledger.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus-server/src/tasks/trust_ledger.py corvus-server/tests/test_trust_ledger.py
git commit -m "feat(#8): trust ledger core — record outcomes, promotion, demotion"
```

---

### Task 3: Build trust ledger API router

**Files:**
- Create: `corvus-server/src/routers/trust.py`
- Modify: `corvus-server/src/app.py`
- Add to: `corvus-server/tests/test_trust_ledger.py`

**Step 1: Write the failing tests**

Add to `corvus-server/tests/test_trust_ledger.py`:

```python
from tests.conftest import client  # noqa: F401


class TestTrustAPI:

    @pytest.mark.asyncio
    async def test_get_trust_ledger_empty(self, client):
        """GET /ops/trust should return empty list when no data."""
        resp = await client.get("/ops/trust")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_trust_ledger_with_data(self, client):
        """GET /ops/trust should return ledger entries."""
        # Create some entries via the record_outcome function
        from src.tasks.trust_ledger import record_outcome
        await record_outcome("restart:inference", "success")

        resp = await client.get("/ops/trust")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["action_type"] == "restart:inference"

    @pytest.mark.asyncio
    async def test_get_single_trust_tier(self, client):
        """GET /ops/trust/{action_type} should return single entry."""
        from src.tasks.trust_ledger import record_outcome
        await record_outcome("restart:database", "success")

        resp = await client.get("/ops/trust/restart:database")
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "restart:database"
        assert data["trust_tier"] == "ESCALATE"

    @pytest.mark.asyncio
    async def test_get_unknown_trust_tier(self, client):
        """GET /ops/trust/{action_type} for unknown type should return defaults."""
        resp = await client.get("/ops/trust/nonexistent:type")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trust_tier"] == "ESCALATE"
        assert data["total_count"] == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python3 -m pytest tests/test_trust_ledger.py::TestTrustAPI -v`
Expected: FAIL — 404 on `/ops/trust`

**Step 3: Create the trust router**

Create `corvus-server/src/routers/trust.py`:

```python
"""Trust ledger API endpoints."""

from fastapi import APIRouter

from src.tasks.trust_ledger import get_all_tiers, get_trust_tier

router = APIRouter(prefix="/ops/trust", tags=["trust"])


@router.get("")
async def list_trust_ledger():
    """Get the full trust ledger — all action types with tiers and stats."""
    return await get_all_tiers()


@router.get("/{action_type:path}")
async def get_action_trust(action_type: str):
    """Get trust tier for a specific action type."""
    return await get_trust_tier(action_type)
```

**Step 4: Register in app.py**

In `corvus-server/src/app.py`, add:

```python
from src.routers import backup, changes, cmdb, events, incidents, metrics, problems, runbooks, trust
# ...
app.include_router(trust.router)
```

**Step 5: Run tests**

Run: `cd corvus-server && python3 -m pytest tests/test_trust_ledger.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus-server/src/routers/trust.py corvus-server/src/app.py corvus-server/tests/test_trust_ledger.py
git commit -m "feat(#8): trust ledger API — GET /ops/trust endpoints"
```

---

### Task 4: Add trust tier to target status + metrics + gap detection

**Files:**
- Modify: `corvus-server/src/routers/events.py` (target status)
- Modify: `corvus-server/src/routers/metrics.py` (trust metrics)
- Modify: `corvus-server/src/tasks/gap_detection.py` (stuck-escalation gap)
- Add to: `corvus-server/tests/test_trust_ledger.py`

**Step 1: Write the failing tests**

Add to `corvus-server/tests/test_trust_ledger.py`:

```python
class TestTrustIntegration:

    @pytest.mark.asyncio
    async def test_target_status_includes_trust(self, client):
        """Target status should include trust tier info."""
        # Register service
        await client.post("/ops/cmdb/register", json={
            "name": "vllm-primary",
            "host": "host-04",
            "service_type": "inference",
        })

        resp = await client.get("/ops/events/targets/vllm-primary/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "trust_tier" in data

    @pytest.mark.asyncio
    async def test_metrics_include_trust_tiers(self, client):
        """GET /ops/metrics should include trust tier counts."""
        resp = await client.get("/ops/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "trust_tiers" in data
        assert "recent_promotions" in data
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python3 -m pytest tests/test_trust_ledger.py::TestTrustIntegration -v`
Expected: FAIL — `trust_tier` not in target status response

**Step 3: Add trust tier to target status**

In `corvus-server/src/routers/events.py`, in the `get_target_status` function, after looking up the CMDB entry for service_type, add a trust tier lookup:

```python
# Look up trust tier for this target's common action types
from src.tasks.trust_ledger import get_trust_tier as _get_trust
trust_info = None
if target:
    # Get service_type from CMDB
    cursor = await db.execute(
        "SELECT service_type FROM ops_cmdb WHERE name = ?", (target,)
    )
    cmdb_row = await cursor.fetchone()
    if cmdb_row and cmdb_row["service_type"]:
        svc_type = cmdb_row["service_type"]
        trust_info = await _get_trust(f"remediation.restart:{svc_type}")
```

Then include `trust_tier` in the response:

```python
return TargetStatus(
    target=target,
    recommendation=recommendation,
    reason=reason,
    active_changes=active_changes,
    active_incidents=active_incidents,
    recent_events=recent_events,
    trust_tier=trust_info["trust_tier"] if trust_info else "ESCALATE",
)
```

Add `trust_tier` to the `TargetStatus` model in `corvus-server/src/models/events.py`:

```python
class TargetStatus(BaseModel):
    target: str
    recommendation: str
    reason: str
    active_changes: list[dict[str, Any]] = []
    active_incidents: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []
    trust_tier: str = "ESCALATE"
```

**Step 4: Add trust metrics**

In `corvus-server/src/routers/metrics.py`, add before `return metrics`:

```python
# Trust ledger stats
cursor = await db.execute(
    "SELECT trust_tier, COUNT(*) as cnt FROM ops_trust_ledger GROUP BY trust_tier"
)
rows = await cursor.fetchall()
metrics["trust_tiers"] = {r["trust_tier"]: r["cnt"] for r in rows}

# Recent promotions (last 7 days)
cursor = await db.execute(
    "SELECT action_type, trust_tier, promoted_at FROM ops_trust_ledger "
    "WHERE promoted_at IS NOT NULL AND promoted_at >= ?",
    (last_7d,),
)
rows = await cursor.fetchall()
metrics["recent_promotions"] = [
    {"action_type": r["action_type"], "trust_tier": r["trust_tier"],
     "promoted_at": r["promoted_at"]}
    for r in rows
]
```

**Step 5: Add stuck-escalation gap detection**

In `corvus-server/src/tasks/gap_detection.py`, add a new function:

```python
async def check_trust_gaps() -> list[str]:
    """Check for action types stuck at ESCALATE with no executions for 30d."""
    db = await get_db()
    created_problems: list[str] = []
    try:
        now = datetime.now(UTC)
        thirty_days_ago = (now - timedelta(days=30)).isoformat()

        # Find action types at ESCALATE that haven't been executed recently
        cursor = await db.execute(
            """SELECT action_type FROM ops_trust_ledger
               WHERE trust_tier = 'ESCALATE' AND total_count > 0"""
        )
        stuck = await cursor.fetchall()

        for row in stuck:
            action_type = row["action_type"]
            # Check if any recent triage for this action type
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM ops_triage_log "
                "WHERE action_type = ? AND timestamp >= ?",
                (action_type, thirty_days_ago),
            )
            recent = await cursor.fetchone()
            if recent["cnt"] == 0:
                pid = await _create_gap(
                    db,
                    now.isoformat(),
                    title=f"Action type stuck at ESCALATE: {action_type}",
                    pattern=f"gap:autonomy:stuck-escalation:{action_type}",
                    root_cause=f"No executions in 30 days for {action_type}",
                    recommended_fix="CI: Review whether this action type is still relevant",
                    workstream="CI",
                )
                if pid:
                    created_problems.append(pid)

        if created_problems:
            await db.commit()
        return created_problems
    finally:
        await db.close()
```

Add `from datetime import timedelta` to imports if not already present.

**Step 6: Run tests**

Run: `cd corvus-server && python3 -m pytest tests/test_trust_ledger.py -v`
Expected: All PASS

**Step 7: Run full quality gates**

```bash
cd corvus-server
ruff check src/ tests/
ruff format --check src/ tests/
bandit -r src/ -c pyproject.toml
python3 -m pytest tests/ -v --ignore=tests/test_mcp_server.py
```
Expected: All PASS

**Step 8: Commit**

```bash
git add corvus-server/src/routers/events.py corvus-server/src/models/events.py corvus-server/src/routers/metrics.py corvus-server/src/tasks/gap_detection.py corvus-server/tests/test_trust_ledger.py
git commit -m "feat(#8): trust tier in target status, metrics, and gap detection"
```

---

### Task 5: Final — quality gates and PR

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
git push -u origin feat/issue-8-trust-ledger
gh pr create --title "feat: trust ledger — action-type tracking + auto-promotion (#8)" \
  --body "$(cat <<'EOF'
## Summary
- New `ops_trust_ledger` table tracks per-action-type success/failure rates
- Trust tiers: ESCALATE → SUPERVISED → AUTO
- Promotion: >95% success over 20+ executions
- Demotion: any failure at AUTO → SUPERVISED
- `GET /ops/trust` — full ledger; `GET /ops/trust/{action_type}` — single entry
- Target status API includes `trust_tier` field
- `GET /ops/metrics` includes `trust_tiers` counts and `recent_promotions`
- Gap detection: stuck-escalation gap for 30d idle action types

Closes #8

## Test plan
- [ ] `pytest tests/test_trust_ledger.py -v` — all trust tests pass
- [ ] `pytest tests/ -v` — full suite, no regressions
- [ ] `ruff check src/ tests/` — clean
- [ ] `bandit -r src/ -c pyproject.toml` — clean
EOF
)"
```
