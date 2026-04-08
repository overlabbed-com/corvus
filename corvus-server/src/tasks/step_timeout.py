"""Background task: reap timed-out plan steps.

Runs periodically to detect steps stuck in 'executing' state past their
timeout. Re-queues or fails them based on retry limits.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from src.database import get_db
from src.tasks.task_metrics import track_task

logger = logging.getLogger(__name__)


async def reap_timed_out_steps() -> int:
    """Reap steps stuck in executing state past their timeout.

    Returns count of reaped steps.
    """
    db = await get_db()
    try:
        now = datetime.now(UTC)

        # Find executing plan steps past their timeout
        cursor = await db.execute(
            "SELECT * FROM ops_plan_steps WHERE status = 'executing' AND started_at IS NOT NULL"
        )
        rows = await cursor.fetchall()

        reaped = 0
        for row in rows:
            started = datetime.fromisoformat(row["started_at"])
            elapsed = (now - started).total_seconds()
            if elapsed < row["timeout"]:
                continue

            retry_count = row["retry_count"] + 1

            if retry_count <= row["max_retries"]:
                # Re-queue
                await db.execute(
                    "UPDATE ops_plan_steps SET status = 'ready', started_at = NULL, retry_count = ? WHERE id = ?",
                    (retry_count, row["id"]),
                )
                logger.info(
                    "Re-queued timed-out step %s (retry %d/%d)",
                    row["id"],
                    retry_count,
                    row["max_retries"],
                )
            else:
                # Exhausted retries — apply failure_policy
                now_iso = now.isoformat()

                if row["failure_policy"] == "skip":
                    # Skip: mark as skipped, don't block the plan
                    await db.execute(
                        "UPDATE ops_plan_steps SET status = 'skipped', error = 'Step timed out', "
                        "completed_at = ?, retry_count = ? WHERE id = ?",
                        (now_iso, retry_count, row["id"]),
                    )
                    logger.info(
                        "Skipped timed-out step %s (skip policy)",
                        row["id"],
                    )
                else:
                    # halt (default) or retry (exhausted) — fail and block
                    await db.execute(
                        "UPDATE ops_plan_steps SET status = 'failed', error = 'Step timed out', "
                        "completed_at = ?, retry_count = ? WHERE id = ?",
                        (now_iso, retry_count, row["id"]),
                    )

                    # Block the plan
                    await db.execute(
                        "UPDATE ops_plans SET status = 'blocked' WHERE id = ? AND status = 'executing'",
                        (row["plan_id"],),
                    )
                    # Emit plan.blocked event
                    event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
                    await db.execute(
                        """INSERT INTO ops_events (id, timestamp, source, type, target, severity, data)
                           VALUES (?, ?, 'corvus', 'plan.blocked', ?, 'warning', ?)""",
                        (
                            event_id,
                            now_iso,
                            row["plan_id"],
                            json.dumps(
                                {
                                    "summary": f"Step {row['name']} timed out after {int(elapsed)}s",
                                    "step_id": row["id"],
                                }
                            ),
                        ),
                    )
                    logger.warning(
                        "Step %s timed out, plan %s blocked",
                        row["id"],
                        row["plan_id"],
                    )

            reaped += 1

        if reaped:
            await db.commit()
        return reaped
    finally:
        await db.close()


async def run_step_timeout_loop(interval_seconds: int = 60):
    """Run step timeout check every interval_seconds (default 1 min)."""
    while True:
        try:
            with track_task("step_timeout") as ctx:
                count = await reap_timed_out_steps()
                ctx["count"] = count
            if count:
                logger.info("Reaped %d timed-out steps", count)
        except Exception:
            logger.exception("Error in step timeout reaper")
        await asyncio.sleep(interval_seconds)
