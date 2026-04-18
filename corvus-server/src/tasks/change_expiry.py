"""Background task: expire stale change windows.

Runs periodically to transition active change windows past their
expires_at timestamp to 'expired' status.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from src.database import get_db
from src.tasks.task_metrics import track_task

logger = logging.getLogger(__name__)


async def expire_stale_changes() -> int:
    """Expire change windows past their expiry time.

    Returns count of expired changes.
    """
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()

        cursor = await db.execute(
            """SELECT id, targets, created_by FROM ops_changes
               WHERE status = 'active' AND auto_expire = 1
               AND expires_at IS NOT NULL AND expires_at < ?""",
            (now,),
        )
        rows = await cursor.fetchall()

        expired_count = 0
        for row in rows:
            await db.execute(
                "UPDATE ops_changes SET status = 'expired', completed_at = ? WHERE id = ?",
                (now, row["id"]),
            )

            # Emit expiry event (one per target)
            targets = json.loads(row["targets"])
            for target in targets:
                event_id = f"EVT-{uuid.uuid4().hex.upper()}"
                await db.execute(
                    """INSERT INTO ops_events
                       (id, timestamp, source, type, target, severity, data,
                        related_change_id)
                       VALUES (?, ?, 'corvus', 'change.expired', ?, 'info', ?, ?)""",
                    (
                        event_id,
                        now,
                        target,
                        json.dumps(
                            {
                                "summary": f"Change {row['id']} expired",
                                "created_by": row["created_by"],
                            }
                        ),
                        row["id"],
                    ),
                )

            expired_count += 1
            logger.info("Expired change window %s", row["id"])

        if expired_count:
            await db.commit()

        return expired_count
    finally:
        await db.close()


async def run_change_expiry_loop(interval_seconds: int = 300):
    """Run change expiry check every interval_seconds (default 5 min)."""
    while True:
        try:
            with track_task("change_expiry") as ctx:
                count = await expire_stale_changes()
                ctx["count"] = count
            if count:
                logger.info("Expired %d stale change windows", count)
        except Exception:
            logger.exception("Error in change expiry task")
        await asyncio.sleep(interval_seconds)
