"""Lean metrics collector — computes operational metrics from source tables.

Runs every 15 minutes. Computes three tiers of metrics:
- Tier 1: Value stream (cycle time, lead time, queue time)
- Tier 2: Throughput & capacity (takt time, WIP, throughput rates)
- Tier 3: Efficiency & quality (hit rate, false positive rate, timeout rate)
"""

import asyncio
import json
import logging
import uuid
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
            "SELECT created_at, resolved_at FROM ops_incidents WHERE status = 'resolved' AND resolved_at >= ?",
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
            "SELECT created_at, completed_at FROM ops_changes WHERE status = 'completed' AND completed_at >= ?",
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
            "SELECT created_at, completed_at FROM ops_plans WHERE status = 'completed' AND completed_at >= ?",
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
            "SELECT created_at, approved_at FROM ops_plans WHERE approved_at IS NOT NULL AND approved_at >= ?",
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
            "SELECT started_at, completed_at FROM ops_plan_steps WHERE status = 'completed' AND completed_at >= ?",
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


async def collect_throughput_metrics(lookback_hours: int = 24) -> dict:
    """Tier 2: Throughput & capacity — demand vs. capacity."""
    since = (datetime.now(UTC) - timedelta(hours=lookback_hours)).isoformat()
    window_seconds = lookback_hours * 3600
    metrics: dict = {}
    db = await get_db()
    try:
        # Resolved incidents in window
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_incidents WHERE status = 'resolved' AND resolved_at >= ?",
            (since,),
        )
        resolved = (await cursor.fetchone())["cnt"]
        metrics["incidents_resolved"] = resolved
        metrics["incident_takt_time"] = window_seconds / resolved if resolved else 0

        # Completed plans in window
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_plans WHERE status = 'completed' AND completed_at >= ?",
            (since,),
        )
        plans_done = (await cursor.fetchone())["cnt"]
        metrics["plans_completed"] = plans_done

        # Steps executed in window
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_plan_steps WHERE status = 'completed' AND completed_at >= ?",
            (since,),
        )
        metrics["steps_executed"] = (await cursor.fetchone())["cnt"]

        # Triages completed in window
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE outcome != 'pending' AND outcome_at >= ?",
            (since,),
        )
        triages_done = (await cursor.fetchone())["cnt"]
        metrics["triages_completed"] = triages_done
        metrics["triage_takt_time"] = window_seconds / triages_done if triages_done else 0

        # WIP: active items right now (not windowed)
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_incidents WHERE status NOT IN ('resolved', 'closed')"
        )
        wip_incidents = (await cursor.fetchone())["cnt"]
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_changes WHERE status = 'active'")
        wip_changes = (await cursor.fetchone())["cnt"]
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_plans WHERE status = 'executing'")
        wip_plans = (await cursor.fetchone())["cnt"]
        metrics["wip"] = wip_incidents + wip_changes + wip_plans

        return metrics
    finally:
        await db.close()


async def collect_efficiency_metrics(lookback_hours: int = 24) -> dict:
    """Tier 3: Efficiency & quality — how well is the system working?"""
    since = (datetime.now(UTC) - timedelta(hours=lookback_hours)).isoformat()
    metrics: dict = {}
    db = await get_db()
    try:
        from src.config import RuntimeConfig

        threshold = RuntimeConfig.get("triage.confidence_threshold")

        # Triage hit rate (confidence > threshold)
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_triage_log WHERE outcome_at >= ?", (since,))
        total = (await cursor.fetchone())["cnt"]
        if total > 0:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE confidence > ? AND outcome_at >= ?",
                (threshold, since),
            )
            hits = (await cursor.fetchone())["cnt"]
            metrics["triage_hit_rate"] = round(hits / total * 100, 1)
        else:
            metrics["triage_hit_rate"] = 0.0

        # Plan step timeout rate
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_plan_steps WHERE completed_at >= ?",
            (since,),
        )
        total_steps = (await cursor.fetchone())["cnt"]
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_plan_steps "
            "WHERE status = 'failed' AND error LIKE '%timeout%' AND completed_at >= ?",
            (since,),
        )
        timeouts = (await cursor.fetchone())["cnt"]
        metrics["timeout_rate"] = round(timeouts / total_steps * 100, 1) if total_steps else 0.0

        # Rollback rate
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_plans WHERE completed_at >= ?",
            (since,),
        )
        total_plans = (await cursor.fetchone())["cnt"]
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_plans WHERE outcome = 'rolled_back' AND completed_at >= ?",
            (since,),
        )
        rollbacks = (await cursor.fetchone())["cnt"]
        metrics["rollback_rate"] = round(rollbacks / total_plans * 100, 1) if total_plans else 0.0

        # Escalation rate
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE escalation_required = 1 AND outcome_at >= ?",
            (since,),
        )
        escalations = (await cursor.fetchone())["cnt"]
        metrics["escalation_rate"] = round(escalations / total * 100, 1) if total else 0.0

        # Task timing stats (from in-memory buffers)
        from src.tasks.task_metrics import get_siem_latency_stats, get_task_stats

        metrics["task_stats"] = get_task_stats()
        metrics["siem_latency"] = get_siem_latency_stats()

        return metrics
    finally:
        await db.close()


async def store_snapshot(tier: str, metrics: dict) -> str:
    """Store a metrics snapshot in the database."""
    now = datetime.now(UTC)
    snapshot_id = f"MSNAP-{uuid.uuid4().hex[:8].upper()}"
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO ops_metrics_snapshots (id, timestamp, period_start, period_end, tier, metrics) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                now.isoformat(),
                (now - timedelta(minutes=15)).isoformat(),
                now.isoformat(),
                tier,
                json.dumps(metrics),
            ),
        )
        await db.commit()
        return snapshot_id
    finally:
        await db.close()


async def run_metrics_collector_loop(interval_seconds: int = 900):
    """Collect all metric tiers every 15 minutes and store snapshots."""
    import time as time_module

    while True:
        try:
            start = time_module.monotonic()

            vs = await collect_value_stream_metrics(lookback_hours=1)
            tp = await collect_throughput_metrics(lookback_hours=24)
            ef = await collect_efficiency_metrics(lookback_hours=24)

            elapsed = time_module.monotonic() - start

            await store_snapshot("value_stream", vs)
            await store_snapshot("throughput", tp)
            await store_snapshot("efficiency", ef)

            logger.info(
                "Metrics collection complete in %.1fs: vs=%d tp=%d ef=%d",
                elapsed,
                len(vs),
                len(tp),
                len(ef),
            )

            # Circuit breaker: if collection > 10s, log warning
            if elapsed > 10:
                logger.warning("Metrics collection took %.1fs — skipping auto-tuning", elapsed)
            else:
                from src.tasks.auto_tuner import run_auto_tuner

                count = await run_auto_tuner({"value_stream": vs, "throughput": tp, "efficiency": ef})
                if count:
                    logger.info("Auto-tuner applied %d adjustments", count)

        except Exception:
            logger.exception("Error in metrics collector")
        await asyncio.sleep(interval_seconds)
