"""Story 6.3: Performance baselines.

Collect and track performance baselines from production data.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class PerformanceBaselines:
    """Track and maintain performance baselines."""

    def __init__(self):
        self._interval = 3600  # Check hourly
        self._history_days = 30  # Keep 30 days of history

    async def collect_metrics(self) -> dict[str, Any]:
        """Collect current performance metrics.

        Story 6.3: Gather baseline data from production.
        """
        from src.database import get_db
        from src.tasks.gap_detection import get_gap_summary

        db = await get_db()
        try:
            # Event throughput
            cursor = await db.execute(
                """SELECT COUNT(*) as count,
                          AVG(strftime('%s', timestamp)) as avg_ts
                   FROM ops_events
                   WHERE timestamp > datetime('now', '-1 hour')"""
            )
            row = await cursor.fetchone()
            events_per_hour = row["count"] if row else 0

            # Triage duration (if available)
            cursor = await db.execute(
                """SELECT AVG(julianday(completed_at) - julianday(created_at)) * 86400 as avg_seconds
                   FROM ops_triage_log
                   WHERE completed_at IS NOT NULL
                   AND completed_at > datetime('now', '-24 hours')"""
            )
            row = await cursor.fetchone()
            avg_triage_seconds = row["avg_seconds"] if row and row["avg_seconds"] else None

            # Gap metrics
            gap_summary = await get_gap_summary()

            # SIEM forwarding stats
            from src.siem.forwarder import get_forwarding_stats

            siem_stats = await get_forwarding_stats()

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "events_per_hour": events_per_hour,
                "avg_triage_seconds": avg_triage_seconds,
                "gaps_open": gap_summary.get("total_open_gaps", 0),
                "siem_forwarding": siem_stats,
            }
        finally:
            await db.close()

    async def store_baseline(self, metrics: dict[str, Any]) -> bool:
        """Store collected metrics for baseline analysis."""
        import json

        from src.database import get_db

        try:
            db = await get_db()
            try:
                await db.execute(
                    """INSERT INTO ops_metrics_snapshots
                       (id, timestamp, period_start, period_end, tier, metrics)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        f"SNAP-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
                        metrics["timestamp"],
                        metrics["timestamp"],
                        metrics["timestamp"],
                        "production",
                        json.dumps(metrics),
                    ),
                )
                await db.commit()
                return True
            finally:
                await db.close()
        except Exception as e:
            logger.error(f"Failed to store baseline: {e}")
            return False

    async def calculate_baselines(self) -> dict[str, Any]:
        """Calculate performance baselines from historical data.

        Returns average, p50, p95, p99 metrics.
        """
        from src.database import get_db

        db = await get_db()
        try:
            # Get last 30 days of snapshots
            cursor = await db.execute(
                """SELECT metrics FROM ops_metrics_snapshots
                   WHERE timestamp > datetime('now', '-30 days')
                   ORDER BY timestamp"""
            )
            rows = await cursor.fetchall()

            if not rows:
                return {"status": "insufficient_data", "days_collected": 0}

            # Extract and analyze
            event_rates = []
            triage_times = []

            for row in rows:
                import json

                metrics = json.loads(row["metrics"])
                if "events_per_hour" in metrics:
                    event_rates.append(metrics["events_per_hour"])
                if "avg_triage_seconds" in metrics and metrics["avg_triage_seconds"]:
                    triage_times.append(metrics["avg_triage_seconds"])

            def calc_stats(values: list[float]) -> dict[str, float]:
                if not values:
                    return {}
                sorted_vals = sorted(values)
                n = len(sorted_vals)
                return {
                    "min": sorted_vals[0],
                    "max": sorted_vals[-1],
                    "avg": sum(values) / n,
                    "p50": sorted_vals[int(n * 0.5)],
                    "p95": sorted_vals[int(n * 0.95)] if n > 20 else sorted_vals[-1],
                    "p99": sorted_vals[int(n * 0.99)] if n > 100 else sorted_vals[-1],
                }

            return {
                "status": "complete",
                "days_collected": len(rows),
                "events_per_hour": calc_stats(event_rates),
                "triage_seconds": calc_stats(triage_times),
            }
        finally:
            await db.close()


async def run_performance_baseline_collection():
    """Run performance baseline collection background task."""
    collector = PerformanceBaselines()

    while True:
        try:
            metrics = await collector.collect_metrics()
            await collector.store_baseline(metrics)

            # Calculate baselines daily
            if datetime.now(UTC).hour == 0:
                baselines = await collector.calculate_baselines()
                logger.info(f"Performance baselines: {baselines}")

        except Exception as e:
            logger.error(f"Baseline collection error: {e}")

        await asyncio.sleep(collector._interval)
