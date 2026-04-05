"""Tests for signal quality — baseline behavior, severity scoring, FP tracking.

Covers both the original signal_quality module and the new Issue #5 additions:
- baseline_checker.check_baseline()
- severity_scorer.score_severity()
- POST /ops/cmdb/{name}/baseline endpoint
- GET /ops/metrics with baseline_coverage and false_positive_rate_by_service_type
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.database import get_db
from src.tasks.signal_quality import (
    get_false_positive_stats,
    get_service_baseline,
    is_expected_behavior,
    populate_default_baselines,
    score_severity,
)

# ── Original signal_quality tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_baseline_unknown_service(client):
    """Unknown service returns global default baseline."""
    baseline = await get_service_baseline("nonexistent-service")
    assert baseline["source"] == "default"


@pytest.mark.asyncio
async def test_baseline_from_service_type(client):
    """Service with service_type but no custom baseline uses type default."""
    await client.post(
        "/ops/cmdb/register",
        json={"name": "test-proxy", "service_type": "proxy", "host": "test"},
    )
    baseline = await get_service_baseline("test-proxy")
    assert baseline["source"] == "service_type_default"
    assert baseline["expected_restarts_per_day"] == 0
    assert baseline["noise_level"] == "low"


@pytest.mark.asyncio
async def test_baseline_from_cmdb(client):
    """Service with custom CMDB baseline uses that."""
    custom = {"expected_restarts_per_day": 24, "noise_level": "high", "expected_events": ["remediation.restart"]}
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ops_cmdb (id, name, service_type, host, baseline_behavior, created_at)
               VALUES ('test-1', 'certbot', 'utility', 'test', ?, ?)""",
            (json.dumps(custom), datetime.now(UTC).isoformat()),
        )
        await db.commit()
    finally:
        await db.close()

    baseline = await get_service_baseline("certbot")
    assert baseline["source"] == "cmdb"
    assert baseline["expected_restarts_per_day"] == 24


@pytest.mark.asyncio
async def test_expected_behavior_match(client):
    """Event matching baseline returns expected=True."""
    custom = {"expected_events": ["remediation.restart"]}
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ops_cmdb (id, name, service_type, host, baseline_behavior, created_at)
               VALUES ('test-2', 'autoheal', 'utility', 'test', ?, ?)""",
            (json.dumps(custom), datetime.now(UTC).isoformat()),
        )
        await db.commit()
    finally:
        await db.close()

    result = await is_expected_behavior("autoheal", "remediation.restart")
    assert result["expected"] is True


@pytest.mark.asyncio
async def test_expected_behavior_silent_policy(client):
    """Service with alert_policy=silent always returns expected=True."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ops_cmdb (id, name, service_type, host, alert_policy, baseline_behavior, created_at)
               VALUES ('test-3', 'test-silent', 'utility', 'test', 'silent', '{}', ?)""",
            (datetime.now(UTC).isoformat(),),
        )
        await db.commit()
    finally:
        await db.close()

    result = await is_expected_behavior("test-silent", "incident.opened")
    assert result["expected"] is True


@pytest.mark.asyncio
async def test_severity_scoring_base(client):
    """Severity scoring returns base score for unknown service."""
    result = await score_severity("unknown-service", "warning")
    assert result["score"] == 2
    assert result["effective_severity"] == "warning"


@pytest.mark.asyncio
async def test_severity_scoring_critical_service(client):
    """Critical service gets severity bump."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ops_cmdb (id, name, service_type, host, critical, created_at)
               VALUES ('test-4', 'caddy-test', 'proxy', 'test', 1, ?)""",
            (datetime.now(UTC).isoformat(),),
        )
        await db.commit()
    finally:
        await db.close()

    result = await score_severity("caddy-test", "warning")
    assert result["score"] == 3  # warning(2) + critical(1)
    assert result["effective_severity"] == "high"
    assert result["factors"]["critical_service"] is True


@pytest.mark.asyncio
async def test_false_positive_stats_empty(client):
    """Empty DB returns 0% FP rate."""
    stats = await get_false_positive_stats(days=7)
    assert stats["total_resolved"] == 0
    assert stats["false_positive_rate"] == 0.0


@pytest.mark.asyncio
async def test_false_positive_stats_with_data(client):
    """FP rate calculated correctly from resolved incidents."""
    db = await get_db()
    try:
        now = datetime.now(UTC)
        # Real incident (has remediation)
        await db.execute(
            """INSERT INTO ops_incidents
               (id, created_at, detected_by, target, status, severity, title,
                remediation_applied, resolved_at, resolution_time_minutes)
               VALUES ('INC-REAL', ?, 'test', 'svc-a', 'resolved', 'warning',
                       'Real issue', 'Restarted service', ?, 15)""",
            ((now - timedelta(hours=2)).isoformat(), now.isoformat()),
        )
        # False positive (no remediation)
        await db.execute(
            """INSERT INTO ops_incidents
               (id, created_at, detected_by, target, status, severity, title,
                resolved_at, resolution_time_minutes)
               VALUES ('INC-FP', ?, 'test', 'svc-b', 'resolved', 'warning',
                       'Noise', ?, 2)""",
            ((now - timedelta(hours=1)).isoformat(), now.isoformat()),
        )
        await db.commit()
    finally:
        await db.close()

    stats = await get_false_positive_stats(days=7)
    assert stats["total_resolved"] == 2
    assert stats["false_positives"] == 1
    assert stats["false_positive_rate"] == 50.0
    assert "svc-b" in stats["by_target"]


@pytest.mark.asyncio
async def test_populate_baselines(client):
    """Populate baselines updates services with empty baselines."""
    await client.post(
        "/ops/cmdb/register",
        json={"name": "test-infer", "service_type": "inference", "host": "test"},
    )
    result = await populate_default_baselines()
    assert result["updated"] >= 1

    baseline = await get_service_baseline("test-infer")
    assert baseline["source"] == "cmdb"  # Now has a custom baseline


@pytest.mark.asyncio
async def test_signal_quality_endpoint(client):
    """GET /ops/signal-quality returns FP stats."""
    resp = await client.get("/ops/signal-quality")
    assert resp.status_code == 200
    data = resp.json()
    assert "false_positive_rate" in data
    assert "total_resolved" in data


@pytest.mark.asyncio
async def test_baseline_endpoint(client):
    """GET /ops/baselines/{service} returns baseline."""
    resp = await client.get("/ops/baselines/nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert "source" in data


@pytest.mark.asyncio
async def test_check_expected_endpoint(client):
    """GET /ops/baselines/{service}/check returns expected behavior."""
    resp = await client.get("/ops/baselines/nonexistent/check?event_type=test.event")
    assert resp.status_code == 200
    data = resp.json()
    assert "expected" in data


# ── Issue #5: baseline_checker tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_baseline_checker_returns_true_for_expected_events(client):
    """Baseline checker returns True when event_type is in expected_events."""
    await client.post(
        "/ops/cmdb/register",
        json={"name": "certbot-bc", "service_type": "utility", "critical": False},
    )
    await client.post(
        "/ops/cmdb/certbot-bc/baseline",
        json={"expected_restarts_per_day": 2, "expected_events": ["remediation.restart"]},
    )

    from src.tasks.baseline_checker import check_baseline

    result = await check_baseline("certbot-bc", "remediation.restart")
    assert result is True


@pytest.mark.asyncio
async def test_baseline_checker_returns_false_for_unexpected_events(client):
    """Baseline checker returns False when event_type is NOT in expected_events."""
    await client.post(
        "/ops/cmdb/register",
        json={"name": "nginx-bc", "service_type": "proxy", "critical": True},
    )
    await client.post(
        "/ops/cmdb/nginx-bc/baseline",
        json={"expected_restarts_per_day": 0, "expected_events": []},
    )

    from src.tasks.baseline_checker import check_baseline

    result = await check_baseline("nginx-bc", "remediation.restart")
    assert result is False


@pytest.mark.asyncio
async def test_baseline_checker_returns_false_for_unknown_targets(client):
    """Baseline checker returns False for targets not in CMDB."""
    from src.tasks.baseline_checker import check_baseline

    result = await check_baseline("nonexistent-service", "remediation.restart")
    assert result is False


# ── Issue #5: severity_scorer tests ───────────────────────────────────


@pytest.mark.asyncio
async def test_severity_scorer_returns_high_for_critical_with_deps(client):
    """Severity scorer returns 'high' for critical services with >= 3 dependencies."""
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "vault-ss",
            "service_type": "secrets",
            "critical": True,
            "dependencies": ["consul", "postgres", "nginx"],
        },
    )

    from src.tasks.severity_scorer import score_severity as simple_score

    result = await simple_score("vault-ss")
    assert result == "high"


@pytest.mark.asyncio
async def test_severity_scorer_returns_low_for_non_critical_utilities(client):
    """Severity scorer returns 'low' for non-critical utility/media services."""
    await client.post(
        "/ops/cmdb/register",
        json={"name": "certbot-ss", "service_type": "utility", "critical": False},
    )

    from src.tasks.severity_scorer import score_severity as simple_score

    result = await simple_score("certbot-ss")
    assert result == "low"


@pytest.mark.asyncio
async def test_severity_scorer_returns_low_for_non_critical_media(client):
    """Severity scorer returns 'low' for non-critical media services."""
    await client.post(
        "/ops/cmdb/register",
        json={"name": "plex-ss", "service_type": "media", "critical": False},
    )

    from src.tasks.severity_scorer import score_severity as simple_score

    result = await simple_score("plex-ss")
    assert result == "low"


@pytest.mark.asyncio
async def test_severity_scorer_returns_medium_as_default(client):
    """Severity scorer returns 'medium' for unknown targets."""
    from src.tasks.severity_scorer import score_severity as simple_score

    result = await simple_score("unknown-service")
    assert result == "medium"


@pytest.mark.asyncio
async def test_severity_scorer_returns_medium_for_critical_no_deps(client):
    """Severity scorer returns 'medium' for critical service with < 3 deps."""
    await client.post(
        "/ops/cmdb/register",
        json={
            "name": "postgres-ss",
            "service_type": "database",
            "critical": True,
            "dependencies": ["storage"],
        },
    )

    from src.tasks.severity_scorer import score_severity as simple_score

    result = await simple_score("postgres-ss")
    assert result == "medium"


@pytest.mark.asyncio
async def test_severity_scorer_returns_medium_for_non_critical_non_utility(client):
    """Severity scorer returns 'medium' for non-critical, non-utility/media services."""
    await client.post(
        "/ops/cmdb/register",
        json={"name": "redis-ss", "service_type": "database", "critical": False},
    )

    from src.tasks.severity_scorer import score_severity as simple_score

    result = await simple_score("redis-ss")
    assert result == "medium"


# ── Issue #5: POST /ops/cmdb/{name}/baseline endpoint ────────────────


@pytest.mark.asyncio
async def test_post_cmdb_baseline_sets_baseline(client):
    """POST /ops/cmdb/{name}/baseline sets baseline_behavior on the service."""
    await client.post(
        "/ops/cmdb/register",
        json={"name": "certbot-ep", "service_type": "utility", "critical": False},
    )

    resp = await client.post(
        "/ops/cmdb/certbot-ep/baseline",
        json={"expected_restarts_per_day": 2, "expected_events": ["remediation.restart"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["baseline_behavior"]["expected_restarts_per_day"] == 2
    assert "remediation.restart" in data["baseline_behavior"]["expected_events"]

    # Verify via GET
    resp = await client.get("/ops/cmdb/certbot-ep")
    assert resp.status_code == 200
    svc = resp.json()
    assert svc["baseline_behavior"]["expected_restarts_per_day"] == 2


@pytest.mark.asyncio
async def test_post_cmdb_baseline_returns_404_for_unknown_service(client):
    """POST /ops/cmdb/{name}/baseline returns 404 for unknown service."""
    resp = await client.post(
        "/ops/cmdb/nonexistent/baseline",
        json={"expected_restarts_per_day": 1, "expected_events": []},
    )
    assert resp.status_code == 404


# ── Issue #5: Extended GET /ops/metrics ───────────────────────────────


@pytest.mark.asyncio
async def test_metrics_includes_baseline_coverage_and_fp_by_service_type(client):
    """GET /ops/metrics includes baseline_coverage and false_positive_rate_by_service_type."""
    # Register services: one with baseline, one without
    await client.post(
        "/ops/cmdb/register",
        json={"name": "certbot-m", "service_type": "utility", "critical": False},
    )
    await client.post(
        "/ops/cmdb/certbot-m/baseline",
        json={"expected_restarts_per_day": 2, "expected_events": ["remediation.restart"]},
    )
    await client.post(
        "/ops/cmdb/register",
        json={"name": "nginx-m", "service_type": "proxy", "critical": True},
    )

    # Create some resolved incidents for FP rate calculation
    now = datetime.now(UTC)
    db = await get_db()
    try:
        # Incident for certbot-m with no remediation (false positive)
        await db.execute(
            """INSERT INTO ops_incidents
               (id, created_at, detected_by, target, status, severity, title,
                remediation_applied, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "inc-fp-m1",
                (now - timedelta(hours=2)).isoformat(),
                "test",
                "certbot-m",
                "resolved",
                "low",
                "certbot restart",
                None,
                now.isoformat(),
            ),
        )
        # Incident for nginx-m with remediation (true positive)
        await db.execute(
            """INSERT INTO ops_incidents
               (id, created_at, detected_by, target, status, severity, title,
                remediation_applied, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "inc-tp-m1",
                (now - timedelta(hours=1)).isoformat(),
                "test",
                "nginx-m",
                "resolved",
                "high",
                "nginx crash",
                "restarted nginx",
                now.isoformat(),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    resp = await client.get("/ops/metrics")
    assert resp.status_code == 200
    data = resp.json()

    # baseline_coverage: 1 of 2 services has baseline -> 50%
    assert "baseline_coverage" in data
    assert data["baseline_coverage"] == 50.0

    # false_positive_rate_by_service_type should exist
    assert "false_positive_rate_by_service_type" in data
    fp_by_type = data["false_positive_rate_by_service_type"]
    # utility: 1 FP / 1 resolved = 100%
    assert fp_by_type.get("utility") == 100.0
    # proxy: 0 FP / 1 resolved = 0%
    assert fp_by_type.get("proxy") == 0.0
