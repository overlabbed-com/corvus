"""Metrics and health endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query

from src.config import RuntimeConfig
from src.database import get_db

router = APIRouter(tags=["metrics"])


@router.get("/ops/health")
async def health_check():
    """System health check."""
    db = await get_db()
    try:
        await db.execute("SELECT 1")
        return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
    finally:
        await db.close()


# NOTE: /ops/metrics/compliance is registered BEFORE /ops/metrics to ensure
# FastAPI matches the more-specific path first (both are exact routes so
# ordering is technically safe, but keeping the specific route first is
# conventional and avoids confusion during review).
@router.get("/ops/metrics/compliance")
async def get_compliance_metrics(
    since: str | None = Query(None, description="ISO8601 timestamp — only audit items after this"),
    source: str | None = Query(None, description="Agent name filter (e.g. my-agent, ops-bot)"),
):
    """Detailed compliance audit -- per-change, per-incident, per-source breakdown.

    Returns:
    - changes: {total, covered, uncovered: [...]}
    - incidents: {total, covered, uncovered: [...]}
    - compliance_rate: overall percentage (changes + incidents)
    - by_source: per-agent compliance breakdown
    """
    from src.tasks.compliance_audit import run_compliance_audit

    db = await get_db()
    try:
        return await run_compliance_audit(db, since=since, source=source)
    finally:
        await db.close()


@router.get("/ops/signal-quality")
async def get_signal_quality(days: int = Query(7, description="Lookback window in days")):
    """Signal quality report — false positive rate, noisy targets, baseline coverage."""
    from src.tasks.signal_quality import get_false_positive_stats

    return await get_false_positive_stats(days=days)


@router.get("/ops/baselines/{service}")
async def get_service_baseline_endpoint(service: str):
    """Get effective baseline behavior for a service."""
    from src.tasks.signal_quality import get_service_baseline

    return await get_service_baseline(service)


@router.post("/ops/baselines/populate")
async def populate_baselines():
    """Populate default baselines for services with known service_types."""
    from src.tasks.signal_quality import populate_default_baselines

    return await populate_default_baselines()


@router.get("/ops/baselines/{service}/check")
async def check_expected_behavior(service: str, event_type: str = Query(..., description="Event type to check")):
    """Check if an event type is expected baseline behavior for a service."""
    from src.tasks.signal_quality import is_expected_behavior

    return await is_expected_behavior(service, event_type)


@router.get("/ops/gaps")
async def get_gaps():
    """Get summary of all open operational gaps."""
    from src.tasks.gap_detection import get_gap_summary

    return await get_gap_summary()


@router.post("/ops/gaps/sweep")
async def run_gap_sweep_endpoint():
    """Manually trigger a gap detection sweep."""
    from src.tasks.gap_detection import run_gap_sweep

    return await run_gap_sweep()


@router.get("/ops/modules")
async def list_modules():
    """List all loaded modules and their status."""
    from src.modules.loader import registry

    return [
        {
            "name": m.manifest.name,
            "version": m.manifest.version,
            "type": m.manifest.type,
            "description": m.manifest.description,
            "active": m.active,
            "has_router": m.router is not None,
            "has_metrics": m.metrics_fn is not None,
            "tools_count": len(m.tools),
        }
        for m in registry.list_all()
    ]


@router.post("/ops/cleanup")
async def run_cleanup(
    dry_run: bool = Query(False, description="Preview what would be deleted without actually deleting"),
):
    """Manually trigger event/audit/triage cleanup.

    Prunes records older than configured retention periods.
    Use dry_run=true to preview counts without deleting.
    """
    from src.tasks.event_cleanup import prune_audit_log, prune_events, prune_triage_log

    events_result = await prune_events(dry_run=dry_run)
    audit_result = await prune_audit_log(dry_run=dry_run)
    triage_result = await prune_triage_log(dry_run=dry_run)
    return {
        "dry_run": dry_run,
        "events": events_result,
        "audit_log": audit_result,
        "triage_log": triage_result,
    }


@router.get("/ops/metrics")
async def get_metrics():
    """Dashboard metrics -- compliance, triage, signal quality, gaps."""
    db = await get_db()
    try:
        now = datetime.now(UTC)
        last_24h = (now - timedelta(hours=24)).isoformat()
        last_7d = (now - timedelta(days=7)).isoformat()

        metrics: dict[str, Any] = {}

        # Event counts
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_events WHERE timestamp >= ?",
            (last_24h,),
        )
        row = await cursor.fetchone()
        metrics["events_24h"] = row["cnt"]

        # Active changes
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_changes WHERE status = 'active'")
        row = await cursor.fetchone()
        metrics["active_changes"] = row["cnt"]

        # Open incidents
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_incidents WHERE status IN ('open', 'investigating')")
        row = await cursor.fetchone()
        metrics["open_incidents"] = row["cnt"]

        # Incidents by severity
        cursor = await db.execute(
            """SELECT severity, COUNT(*) as cnt FROM ops_incidents
               WHERE status IN ('open', 'investigating')
               GROUP BY severity"""
        )
        rows = await cursor.fetchall()
        metrics["incidents_by_severity"] = {r["severity"]: r["cnt"] for r in rows}

        # Resolution time (avg over last 7 days)
        cursor = await db.execute(
            """SELECT AVG(resolution_time_minutes) as avg_time
               FROM ops_incidents
               WHERE resolved_at IS NOT NULL AND resolved_at >= ?""",
            (last_7d,),
        )
        row = await cursor.fetchone()
        metrics["avg_resolution_time_minutes"] = row["avg_time"]

        # Open problems
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_problems WHERE status IN ('identified', 'investigating')"
        )
        row = await cursor.fetchone()
        metrics["open_problems"] = row["cnt"]

        # Gap counts by workstream
        cursor = await db.execute(
            """SELECT workstream, COUNT(*) as cnt FROM ops_problems
               WHERE pattern LIKE 'gap:%' AND status != 'resolved'
               GROUP BY workstream"""
        )
        rows = await cursor.fetchall()
        metrics["gaps_by_workstream"] = {(r["workstream"] or "unrouted"): r["cnt"] for r in rows}

        # CMDB stats
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_cmdb")
        row = await cursor.fetchone()
        metrics["total_services"] = row["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_cmdb WHERE service_type IS NULL")
        row = await cursor.fetchone()
        metrics["untyped_services"] = row["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_cmdb WHERE critical = 1")
        row = await cursor.fetchone()
        metrics["critical_services"] = row["cnt"]

        # False positive rate (incidents resolved with no action in last 7d)
        cursor = await db.execute(
            """SELECT COUNT(*) as cnt FROM ops_incidents
               WHERE resolved_at >= ? AND remediation_applied IS NULL""",
            (last_7d,),
        )
        fp_row = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_incidents WHERE resolved_at >= ?",
            (last_7d,),
        )
        total_resolved = await cursor.fetchone()
        if total_resolved["cnt"] > 0:
            metrics["false_positive_rate"] = round(fp_row["cnt"] / total_resolved["cnt"] * 100, 1)
        else:
            metrics["false_positive_rate"] = 0.0

        # Baseline coverage: % of CMDB services with non-empty baseline_behavior
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_cmdb WHERE baseline_behavior != '{}'")
        baseline_row = await cursor.fetchone()
        if metrics["total_services"] > 0:
            metrics["baseline_coverage"] = round(baseline_row["cnt"] / metrics["total_services"] * 100, 1)
        else:
            metrics["baseline_coverage"] = 0.0

        # False positive rate by service type
        cursor = await db.execute(
            """SELECT c.service_type,
                      COUNT(*) as total,
                      COALESCE(SUM(CASE WHEN i.remediation_applied IS NULL THEN 1 ELSE 0 END), 0) as fp
               FROM ops_incidents i
               LEFT JOIN ops_cmdb c ON i.target = c.name
               WHERE i.resolved_at >= ?
               GROUP BY c.service_type""",
            (last_7d,),
        )
        rows = await cursor.fetchall()
        metrics["false_positive_rate_by_service_type"] = {
            (r["service_type"] or "unknown"): round(r["fp"] / r["total"] * 100, 1) for r in rows if r["total"] > 0
        }

        # SIEM forwarding stats
        from src.siem.forwarder import get_forwarding_stats

        metrics["siem"] = await get_forwarding_stats()

        # Runbook coverage
        from src.runbooks.loader import registry

        metrics["runbook_coverage"] = {
            "covered_service_types": sorted(registry.service_types_covered),
            "total_runbooks": len(registry.list_all()),
        }

        # Triage effectiveness (from ops_triage_log)
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_triage_log")
        row = await cursor.fetchone()
        total_triages = row["cnt"]

        if total_triages > 0:
            # Hit rate: % of triages with confidence > 0.5
            threshold = RuntimeConfig.get("triage.confidence_threshold")
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE confidence > ?",
                (threshold,),
            )
            row = await cursor.fetchone()
            metrics["runbook_hit_rate"] = round(row["cnt"] / total_triages * 100, 1)
        else:
            metrics["runbook_hit_rate"] = 0.0

        # Escalation rate by runbook
        cursor = await db.execute(
            """SELECT runbook_name,
                      COUNT(*) as total,
                      COALESCE(SUM(escalation_required), 0) as escalated
               FROM ops_triage_log
               GROUP BY runbook_name"""
        )
        rows = await cursor.fetchall()
        metrics["escalation_rate_by_runbook"] = {
            r["runbook_name"]: round(r["escalated"] / r["total"] * 100, 1) for r in rows if r["total"] > 0
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
        metrics["avg_resolution_time_by_service_type"] = {r["service_type"]: round(r["avg_time"], 1) for r in rows}

        # Trust ledger stats
        cursor = await db.execute("SELECT trust_tier, COUNT(*) as cnt FROM ops_trust_ledger GROUP BY trust_tier")
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
            {
                "action_type": r["action_type"],
                "trust_tier": r["trust_tier"],
                "promoted_at": r["promoted_at"],
            }
            for r in rows
        ]

        # Compliance instrumentation
        from src.tasks.compliance_audit import run_compliance_audit

        audit = await run_compliance_audit(db)
        metrics["compliance_rate"] = audit["compliance_rate"]

        # Table sizes (for capacity monitoring)
        from src.tasks.event_cleanup import (
            AUDIT_RETENTION_DAYS,
            EVENT_RETENTION_DAYS,
            TRIAGE_RETENTION_DAYS,
            get_table_sizes,
        )

        metrics["table_sizes"] = await get_table_sizes()
        metrics["retention_policy"] = {
            "events_days": EVENT_RETENTION_DAYS,
            "audit_days": AUDIT_RETENTION_DAYS,
            "triage_days": TRIAGE_RETENTION_DAYS,
        }

        return metrics
    finally:
        await db.close()
