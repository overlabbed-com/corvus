"""Tests for gap sweep — blind spot detection and CI/NFI routing."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.database import get_db


@pytest.mark.asyncio
async def test_unseen_service_creates_gap(client):
    """CMDB service with no events in 7+ days should create a gap."""
    # Register a service with old last_seen
    old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    db = await get_db()
    try:
        svc_id = f"SVC-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_cmdb (id, name, host, service_type, last_seen, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (svc_id, "svc-unseen-test", "host1", "inference", old_date, old_date),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_unseen_services

    gaps = await check_unseen_services()
    assert len(gaps) >= 1

    # Verify problem record created
    resp = await client.get("/ops/problems")
    problems = resp.json()
    matching = [p for p in problems if "gap:monitoring:unseen-service:svc-unseen-test" in (p["pattern"] or "")]
    assert len(matching) == 1
    assert matching[0]["workstream"] == "NFI"


@pytest.mark.asyncio
async def test_seen_service_no_gap(client):
    """CMDB service with recent last_seen should NOT create a gap."""
    recent_date = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    db = await get_db()
    try:
        svc_id = f"SVC-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_cmdb (id, name, host, service_type, last_seen, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (svc_id, "svc-seen-test", "host1", "inference", recent_date, recent_date),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_unseen_services

    await check_unseen_services()
    # Should not have created a gap for the recently-seen service
    resp = await client.get("/ops/problems")
    problems = resp.json()
    matching = [p for p in problems if "gap:monitoring:unseen-service:svc-seen-test" in (p["pattern"] or "")]
    assert len(matching) == 0


@pytest.mark.asyncio
async def test_stale_security_finding_creates_gap(client):
    """Problem record with gap:security pattern open 30+ days should create stale-finding gap."""
    old_date = (datetime.now(UTC) - timedelta(days=35)).isoformat()
    db = await get_db()
    try:
        problem_id = f"PRB-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_problems
               (id, created_at, status, title, pattern, root_cause,
                recommended_fix, severity, workstream, correlated_incidents)
               VALUES (?, ?, 'identified', ?, ?, ?, ?, 'high', 'CI', '[]')""",
            (
                problem_id,
                old_date,
                "Old security finding",
                "gap:security:vuln-xyz",
                "Unpatched vulnerability",
                "Apply patch",
            ),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_stale_findings

    gaps = await check_stale_findings()
    assert len(gaps) >= 1

    resp = await client.get("/ops/problems")
    problems = resp.json()
    matching = [p for p in problems if p["pattern"] and p["pattern"].startswith("gap:security:stale-finding:")]
    assert len(matching) >= 1


@pytest.mark.asyncio
async def test_fresh_security_finding_no_gap(client):
    """Problem record with gap:security pattern open < 30 days should NOT create stale gap."""
    recent_date = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    db = await get_db()
    try:
        problem_id = f"PRB-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_problems
               (id, created_at, status, title, pattern, root_cause,
                recommended_fix, severity, workstream, correlated_incidents)
               VALUES (?, ?, 'identified', ?, ?, ?, ?, 'high', 'CI', '[]')""",
            (
                problem_id,
                recent_date,
                "Fresh security finding",
                "gap:security:recent-vuln",
                "Recent vulnerability",
                "Apply patch",
            ),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_stale_findings

    await check_stale_findings()
    # Should not create a stale-finding gap for this fresh problem
    resp = await client.get("/ops/problems")
    problems = resp.json()
    stale_matching = [
        p
        for p in problems
        if p["pattern"] and p["pattern"].startswith("gap:security:stale-finding:") and problem_id in p["pattern"]
    ]
    assert len(stale_matching) == 0


@pytest.mark.asyncio
async def test_generic_fallback_triage_gap(client):
    """Triage with diagnosis 'unknown' and low confidence creates generic-fallback gap."""
    now = datetime.now(UTC).isoformat()
    db = await get_db()
    try:
        triage_id = f"TRG-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_triage_log
               (id, timestamp, target, service_type, runbook_name, action_type,
                diagnosis, confidence, escalation_required, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                triage_id,
                now,
                "svc-fallback-test",
                "inference",
                "generic",
                "unknown:inference",
                "unknown",
                0.2,
                0,
            ),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_triage_gaps

    gaps = await check_triage_gaps(triage_id)
    assert len(gaps) >= 1

    resp = await client.get("/ops/problems")
    problems = resp.json()
    matching = [
        p for p in problems if p["pattern"] and "gap:coverage:generic-fallback:svc-fallback-test" in p["pattern"]
    ]
    assert len(matching) >= 1
    assert matching[0]["workstream"] == "NFI"


@pytest.mark.asyncio
async def test_wrong_recommendation_triage_gap(client):
    """Triage recommendation not matching remediation_applied creates wrong-recommendation gap."""
    now = datetime.now(UTC).isoformat()
    db = await get_db()
    try:
        # Create a triage log with a specific diagnosis
        triage_id = f"TRG-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_triage_log
               (id, timestamp, target, service_type, runbook_name, action_type,
                diagnosis, confidence, escalation_required, outcome,
                related_incident_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', ?)""",
            (
                triage_id,
                now,
                "svc-wrong-rec",
                "inference",
                "inference-runbook",
                "gpu_oom:inference",
                "gpu_oom",
                0.9,
                0,
                None,
            ),
        )
        # Create an incident that was remediated with something different
        inc_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_incidents
               (id, created_at, detected_by, target, status, severity, title,
                remediation_applied)
               VALUES (?, ?, 'test', 'svc-wrong-rec', 'resolved', 'medium',
                       'GPU issue', 'restart_container')""",
            (inc_id, now),
        )
        # Link triage to incident
        await db.execute(
            "UPDATE ops_triage_log SET related_incident_id = ? WHERE id = ?",
            (inc_id, triage_id),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_triage_gaps

    gaps = await check_triage_gaps(triage_id)
    assert len(gaps) >= 1

    resp = await client.get("/ops/problems")
    problems = resp.json()
    matching = [
        p for p in problems if p["pattern"] and "gap:accuracy:wrong-recommendation:svc-wrong-rec" in p["pattern"]
    ]
    assert len(matching) >= 1
    assert matching[0]["workstream"] == "CI"


@pytest.mark.asyncio
async def test_compliance_gap_change_without_event(client):
    """Change without corresponding event creates compliance gap."""
    now = datetime.now(UTC).isoformat()
    db = await get_db()
    try:
        change_id = f"CHG-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_changes
               (id, created_at, created_by, targets, description, status, expires_at)
               VALUES (?, ?, 'claude-code', '["test-svc"]', 'test change', 'completed', ?)""",
            (change_id, now, now),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_compliance_gaps

    gaps = await check_compliance_gaps()
    assert len(gaps) >= 1

    resp = await client.get("/ops/problems")
    problems = resp.json()
    pattern = f"gap:compliance:missing-event:change:{change_id}"
    matching = [p for p in problems if p["pattern"] and pattern in p["pattern"]]
    assert len(matching) == 1
    assert matching[0]["workstream"] == "CI"


@pytest.mark.asyncio
async def test_compliance_gap_incident_without_event(client):
    """Incident without corresponding event creates compliance gap."""
    now = datetime.now(UTC).isoformat()
    db = await get_db()
    try:
        inc_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_incidents
               (id, created_at, detected_by, target, status, severity, title)
               VALUES (?, ?, 'ops-agent', 'test-svc', 'open', 'warning', 'Test incident')""",
            (inc_id, now),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_compliance_gaps

    gaps = await check_compliance_gaps()
    assert len(gaps) >= 1

    resp = await client.get("/ops/problems")
    problems = resp.json()
    pattern = f"gap:compliance:missing-event:incident:{inc_id}"
    matching = [p for p in problems if p["pattern"] and pattern in p["pattern"]]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_compliance_gap_covered_change_no_gap(client):
    """Change WITH a corresponding event should NOT create a compliance gap."""
    now = datetime.now(UTC).isoformat()
    db = await get_db()
    try:
        change_id = f"CHG-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_changes
               (id, created_at, created_by, targets, description, status, expires_at)
               VALUES (?, ?, 'claude-code', '["test-svc"]', 'covered change', 'completed', ?)""",
            (change_id, now, now),
        )
        evt_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_events
               (id, timestamp, source, type, target, severity, data, related_change_id)
               VALUES (?, ?, 'claude-code', 'change.completed', 'test-svc', 'info', '{}', ?)""",
            (evt_id, now, change_id),
        )
        await db.commit()
    finally:
        await db.close()

    from src.tasks.gap_detection import check_compliance_gaps

    await check_compliance_gaps()
    # The covered change should not create a gap
    resp = await client.get("/ops/problems")
    problems = resp.json()
    pattern = f"gap:compliance:missing-event:change:{change_id}"
    matching = [p for p in problems if p["pattern"] and pattern in p["pattern"]]
    assert len(matching) == 0


@pytest.mark.asyncio
async def test_bulk_trust_promotion_sweep(client):
    """Bulk promotion sweep should promote eligible action types."""
    from src.tasks.trust_ledger import run_promotion_sweep

    # Manually insert a ledger entry that qualifies for promotion
    # (bypasses record_outcome which promotes inline)
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ops_trust_ledger
               (action_type, total_count, success_count, failure_count, trust_tier)
               VALUES ('sweep:test:bulk', 25, 25, 0, 'ESCALATE')"""
        )
        await db.commit()
    finally:
        await db.close()

    result = await run_promotion_sweep()
    assert result["promoted"] >= 1
    promotions = [p for p in result["promotions"] if p["action_type"] == "sweep:test:bulk"]
    assert len(promotions) == 1
    assert promotions[0]["from_tier"] == "ESCALATE"
    assert promotions[0]["to_tier"] == "SUPERVISED"


@pytest.mark.asyncio
async def test_bulk_promotion_no_promote_below_threshold(client):
    """Bulk promotion should not promote action types below 95% success rate."""
    from src.tasks.trust_ledger import run_promotion_sweep

    # Manually insert with 90% success rate (below 95% threshold)
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ops_trust_ledger
               (action_type, total_count, success_count, failure_count, trust_tier)
               VALUES ('sweep:test:low', 20, 18, 2, 'ESCALATE')"""
        )
        await db.commit()
    finally:
        await db.close()

    result = await run_promotion_sweep()
    promotions = [p for p in result["promotions"] if p["action_type"] == "sweep:test:low"]
    assert len(promotions) == 0


@pytest.mark.asyncio
async def test_gap_sweep_returns_results(client):
    """Gap sweep orchestrator should return a dict with result counts."""
    from src.tasks.gap_sweep import run_gap_sweep

    results = await run_gap_sweep()
    assert isinstance(results, dict)
    assert "unseen_services" in results
    assert "stale_findings" in results
    assert "cmdb_gaps" in results
    assert "trust_gaps" in results
    assert "compliance_gaps" in results
    assert "trust_promotions" in results
    assert "total_new_gaps" in results


@pytest.mark.asyncio
async def test_post_gaps_sweep_endpoint(client):
    """POST /ops/gaps/sweep should trigger sweep and return results."""
    resp = await client.post("/ops/gaps/sweep")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_new_gaps" in data


@pytest.mark.asyncio
async def test_context_includes_gap_summary(client):
    """GET /ops/events/context should include gap_summary section."""
    resp = await client.get("/ops/events/context")
    assert resp.status_code == 200
    data = resp.json()
    assert "gap_summary" in data
    gap_summary = data["gap_summary"]
    assert "total_open_gaps" in gap_summary
    assert "by_workstream" in gap_summary
