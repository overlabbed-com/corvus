"""Lean metrics API — exposes operational metrics collected by the metrics subsystem.

Six endpoints covering current state, history, throughput, bottlenecks,
auto-tuner adjustments, and convergence status.
"""

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from src.config import RuntimeConfig
from src.database import get_db

router = APIRouter(prefix="/ops/lean-metrics", tags=["lean-metrics"])

# Entity-to-table mapping for throughput bucketing
_ENTITY_CONFIG = {
    "incidents": ("ops_incidents", "resolved_at", "status = 'resolved'"),
    "plans": ("ops_plans", "completed_at", "status = 'completed'"),
    "triages": ("ops_triage_log", "outcome_at", "outcome != 'pending'"),
    "changes": ("ops_changes", "completed_at", "status = 'completed'"),
    "steps": ("ops_plan_steps", "completed_at", "status = 'completed'"),
}


@router.get("")
async def get_current_metrics():
    """Current snapshot — latest metrics per tier (value_stream, throughput, efficiency)."""
    db = await get_db()
    try:
        result = {}
        for tier in ("value_stream", "throughput", "efficiency"):
            cursor = await db.execute(
                "SELECT metrics FROM ops_metrics_snapshots "
                "WHERE tier = ? ORDER BY timestamp DESC LIMIT 1",
                (tier,),
            )
            row = await cursor.fetchone()
            if row:
                result[tier] = json.loads(row["metrics"])
        return result
    finally:
        await db.close()


@router.get("/history")
async def get_history(
    hours: int = Query(24, description="Lookback window in hours"),
    tier: str | None = Query(None, description="Filter by tier"),
):
    """Time series of metric snapshots."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    db = await get_db()
    try:
        if tier:
            cursor = await db.execute(
                "SELECT id, timestamp, period_start, period_end, tier, metrics "
                "FROM ops_metrics_snapshots "
                "WHERE tier = ? AND timestamp >= ? ORDER BY timestamp DESC",
                (tier, since),
            )
        else:
            cursor = await db.execute(
                "SELECT id, timestamp, period_start, period_end, tier, metrics "
                "FROM ops_metrics_snapshots "
                "WHERE timestamp >= ? ORDER BY timestamp DESC",
                (since,),
            )
        rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "period_start": r["period_start"],
                "period_end": r["period_end"],
                "tier": r["tier"],
                "metrics": json.loads(r["metrics"]),
            }
            for r in rows
        ]
    finally:
        await db.close()


@router.get("/throughput")
async def get_throughput(
    entity: str = Query("incidents", description="Entity type: incidents, plans, triages, changes, steps"),
    hours: int = Query(168, description="Lookback window in hours (default 1 week)"),
):
    """Bucketed counts per day for a given entity type."""
    if entity not in _ENTITY_CONFIG:
        raise HTTPException(status_code=422, detail=f"Unknown entity: {entity}. Valid: {', '.join(_ENTITY_CONFIG)}")

    table, ts_col, where_clause = _ENTITY_CONFIG[entity]
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            f"SELECT date({ts_col}) as day, COUNT(*) as count "  # noqa: S608
            f"FROM {table} "
            f"WHERE {where_clause} AND {ts_col} >= ? "
            f"GROUP BY date({ts_col}) "
            f"ORDER BY day DESC",
            (since,),
        )
        rows = await cursor.fetchall()
        return {
            "entity": entity,
            "hours": hours,
            "buckets": [{"day": r["day"], "count": r["count"]} for r in rows],
        }
    finally:
        await db.close()


@router.get("/bottlenecks")
async def get_bottlenecks(
    top_n: int = Query(5, description="Number of bottlenecks to return"),
):
    """Ranked bottlenecks — value stream metrics with largest deviation from 7-day baseline."""
    now = datetime.now(UTC)
    baseline_since = (now - timedelta(days=7)).isoformat()
    db = await get_db()
    try:
        # Get latest value_stream snapshot
        cursor = await db.execute(
            "SELECT metrics FROM ops_metrics_snapshots "
            "WHERE tier = 'value_stream' ORDER BY timestamp DESC LIMIT 1",
        )
        latest_row = await cursor.fetchone()
        if not latest_row:
            return []

        current_metrics = json.loads(latest_row["metrics"])

        # Get all value_stream snapshots in the 7-day window for baseline
        cursor = await db.execute(
            "SELECT metrics FROM ops_metrics_snapshots "
            "WHERE tier = 'value_stream' AND timestamp >= ?",
            (baseline_since,),
        )
        baseline_rows = await cursor.fetchall()

        if not baseline_rows:
            return []

        # Compute rolling P50 baseline per metric
        metric_baselines: dict[str, list[float]] = {}
        for row in baseline_rows:
            snap = json.loads(row["metrics"])
            for key, val in snap.items():
                if isinstance(val, dict) and "p50" in val:
                    metric_baselines.setdefault(key, []).append(val["p50"])

        # Compare current P50 to baseline median P50
        bottlenecks = []
        for key, baseline_values in metric_baselines.items():
            current_val = current_metrics.get(key)
            if not isinstance(current_val, dict) or "p50" not in current_val:
                continue

            current_p50 = current_val["p50"]
            sorted_baselines = sorted(baseline_values)
            baseline_p50 = sorted_baselines[len(sorted_baselines) // 2]

            if baseline_p50 == 0:
                deviation_pct = 0.0 if current_p50 == 0 else 100.0
            else:
                deviation_pct = round((current_p50 - baseline_p50) / baseline_p50 * 100, 1)

            bottlenecks.append({
                "metric": key,
                "current_p50": current_p50,
                "baseline_p50": baseline_p50,
                "deviation_pct": deviation_pct,
            })

        # Rank by largest deviation (slowest relative to baseline)
        bottlenecks.sort(key=lambda x: abs(x["deviation_pct"]), reverse=True)
        return bottlenecks[:top_n]
    finally:
        await db.close()


@router.get("/adjustments")
async def get_adjustments(
    parameter: str | None = Query(None, description="Filter by parameter name"),
    limit: int = Query(50, description="Max results"),
):
    """Audit trail of auto-tuner parameter adjustments."""
    db = await get_db()
    try:
        if parameter:
            cursor = await db.execute(
                "SELECT id, timestamp, parameter, old_value, new_value, "
                "trigger_metric, trigger_value, trigger_threshold, "
                "adjustment_number, dampening_factor, reasoning, "
                "reverted, reverted_at, revert_reason "
                "FROM ops_metric_adjustments "
                "WHERE parameter = ? ORDER BY timestamp DESC LIMIT ?",
                (parameter, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT id, timestamp, parameter, old_value, new_value, "
                "trigger_metric, trigger_value, trigger_threshold, "
                "adjustment_number, dampening_factor, reasoning, "
                "reverted, reverted_at, revert_reason "
                "FROM ops_metric_adjustments "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "parameter": r["parameter"],
                "old_value": r["old_value"],
                "new_value": r["new_value"],
                "trigger_metric": r["trigger_metric"],
                "trigger_value": r["trigger_value"],
                "trigger_threshold": r["trigger_threshold"],
                "adjustment_number": r["adjustment_number"],
                "dampening_factor": r["dampening_factor"],
                "reasoning": r["reasoning"],
                "reverted": bool(r["reverted"]),
                "reverted_at": r["reverted_at"],
                "revert_reason": r["revert_reason"],
            }
            for r in rows
        ]
    finally:
        await db.close()


@router.get("/convergence")
async def get_convergence():
    """Per-parameter convergence status from auto-tuner adjustments."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT parameter, COUNT(*) as adjustment_count, "
            "MAX(timestamp) as latest_timestamp "
            "FROM ops_metric_adjustments "
            "GROUP BY parameter "
            "ORDER BY adjustment_count DESC",
        )
        groups = await cursor.fetchall()

        result = []
        for g in groups:
            # Get latest dampening factor for this parameter
            cursor = await db.execute(
                "SELECT dampening_factor FROM ops_metric_adjustments "
                "WHERE parameter = ? ORDER BY timestamp DESC LIMIT 1",
                (g["parameter"],),
            )
            latest = await cursor.fetchone()
            latest_dampening = latest["dampening_factor"] if latest else 0.0

            # Check RuntimeConfig for current/default values
            try:
                current_value = RuntimeConfig.get(g["parameter"])
                default_value = RuntimeConfig.defaults().get(g["parameter"])
            except KeyError:
                current_value = None
                default_value = None

            result.append({
                "parameter": g["parameter"],
                "adjustment_count": g["adjustment_count"],
                "latest_dampening_factor": latest_dampening,
                "latest_timestamp": g["latest_timestamp"],
                "converged": latest_dampening < 0.05,
                "current_value": current_value,
                "default_value": default_value,
            })

        return result
    finally:
        await db.close()
