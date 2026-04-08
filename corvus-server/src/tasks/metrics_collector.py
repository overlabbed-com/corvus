"""Lean metrics collector — computes operational metrics from source tables.

Runs every 15 minutes. Computes three tiers of metrics:
- Tier 1: Value stream (cycle time, lead time, queue time)
- Tier 2: Throughput & capacity (takt time, WIP, throughput rates)
- Tier 3: Efficiency & quality (hit rate, false positive rate, timeout rate)
"""

import logging
from datetime import UTC, datetime, timedelta

from src.database import get_db

logger = logging.getLogger(__name__)


def _percentiles(values: list[float]) -> dict:
    """Compute percentile summary from a list of values."""
    if not values:
        return {"p50": 0, "p95": 0, "p99": 0, "count": 0}
    s = sorted(values)
    n = len(s)
    return {
        "p50": s[n // 2],
        "p95": s[int(n * 0.95)] if n >= 20 else s[-1],
        "p99": s[int(n * 0.99)] if n >= 100 else s[-1],
        "count": n,
    }


async def collect_value_stream_metrics(lookback_hours: int = 1) -> dict:
    """Tier 1: Value stream metrics — how fast does work flow?"""
    since = (datetime.now(UTC) - timedelta(hours=lookback_hours)).isoformat()
    metrics: dict = {}
    db = await get_db()
    try:
        # Incident cycle time (resolved_at - created_at in seconds)
        cursor = await db.execute(
            "SELECT created_at, resolved_at FROM ops_incidents "
            "WHERE status = 'resolved' AND resolved_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        cycle_times = []
        for r in rows:
            try:
                created = datetime.fromisoformat(r["created_at"])
                resolved = datetime.fromisoformat(r["resolved_at"])
                cycle_times.append((resolved - created).total_seconds())
            except (ValueError, TypeError):
                continue
        metrics["incident_cycle_time"] = _percentiles(cycle_times)

        # Incident queue time (investigating_at - created_at)
        cursor = await db.execute(
            "SELECT created_at, investigating_at FROM ops_incidents "
            "WHERE investigating_at IS NOT NULL AND investigating_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        queue_times = []
        for r in rows:
            try:
                created = datetime.fromisoformat(r["created_at"])
                investigating = datetime.fromisoformat(r["investigating_at"])
                queue_times.append((investigating - created).total_seconds())
            except (ValueError, TypeError):
                continue
        metrics["incident_queue_time"] = _percentiles(queue_times)

        # Triage cycle time
        cursor = await db.execute(
            "SELECT resolution_time_seconds FROM ops_triage_log "
            "WHERE resolution_time_seconds IS NOT NULL AND outcome_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        triage_times = [r["resolution_time_seconds"] for r in rows if r["resolution_time_seconds"]]
        metrics["triage_cycle_time"] = _percentiles(triage_times)

        # Change lead time (completed_at - created_at)
        cursor = await db.execute(
            "SELECT created_at, completed_at FROM ops_changes "
            "WHERE status = 'completed' AND completed_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        change_times = []
        for r in rows:
            try:
                created = datetime.fromisoformat(r["created_at"])
                completed = datetime.fromisoformat(r["completed_at"])
                change_times.append((completed - created).total_seconds())
            except (ValueError, TypeError):
                continue
        metrics["change_lead_time"] = _percentiles(change_times)

        # Plan lead time (completed_at - created_at)
        cursor = await db.execute(
            "SELECT created_at, completed_at FROM ops_plans "
            "WHERE status = 'completed' AND completed_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        plan_times = []
        for r in rows:
            try:
                created = datetime.fromisoformat(r["created_at"])
                completed = datetime.fromisoformat(r["completed_at"])
                plan_times.append((completed - created).total_seconds())
            except (ValueError, TypeError):
                continue
        metrics["plan_lead_time"] = _percentiles(plan_times)

        # Plan approval latency (approved_at - created_at)
        cursor = await db.execute(
            "SELECT created_at, approved_at FROM ops_plans "
            "WHERE approved_at IS NOT NULL AND approved_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        approval_times = []
        for r in rows:
            try:
                created = datetime.fromisoformat(r["created_at"])
                approved = datetime.fromisoformat(r["approved_at"])
                approval_times.append((approved - created).total_seconds())
            except (ValueError, TypeError):
                continue
        metrics["plan_approval_latency"] = _percentiles(approval_times)

        # Step execution time (completed_at - started_at)
        cursor = await db.execute(
            "SELECT started_at, completed_at FROM ops_plan_steps "
            "WHERE status = 'completed' AND completed_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        step_times = []
        for r in rows:
            try:
                started = datetime.fromisoformat(r["started_at"])
                completed = datetime.fromisoformat(r["completed_at"])
                step_times.append((completed - started).total_seconds())
            except (ValueError, TypeError):
                continue
        metrics["step_execution_time"] = _percentiles(step_times)

        # Trust promotion time (promoted_at - first_seen_at)
        cursor = await db.execute(
            "SELECT first_seen_at, promoted_at FROM ops_trust_ledger "
            "WHERE promoted_at IS NOT NULL AND first_seen_at IS NOT NULL AND promoted_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        trust_times = []
        for r in rows:
            try:
                first_seen = datetime.fromisoformat(r["first_seen_at"])
                promoted = datetime.fromisoformat(r["promoted_at"])
                trust_times.append((promoted - first_seen).total_seconds())
            except (ValueError, TypeError):
                continue
        metrics["trust_promotion_time"] = _percentiles(trust_times)

        return metrics
    finally:
        await db.close()
