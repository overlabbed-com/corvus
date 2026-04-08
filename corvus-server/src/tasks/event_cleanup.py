"""Background task: prune old events and audit log entries.

Configurable retention periods. Events older than retention are archived
to JSONL (optional) then deleted. Addresses threat model finding D1.2.
"""

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.database import get_db
from src.tasks.task_metrics import track_task

logger = logging.getLogger(__name__)

# Retention periods (configurable via env)
EVENT_RETENTION_DAYS = int(os.getenv("CORVUS_EVENT_RETENTION_DAYS", "90"))
AUDIT_RETENTION_DAYS = int(os.getenv("CORVUS_AUDIT_RETENTION_DAYS", "365"))
TRIAGE_RETENTION_DAYS = int(os.getenv("CORVUS_TRIAGE_RETENTION_DAYS", "180"))
METRICS_SNAPSHOT_RETENTION_DAYS = int(os.getenv("CORVUS_METRICS_SNAPSHOT_RETENTION_DAYS", "90"))
METRICS_ADJUSTMENT_RETENTION_DAYS = int(os.getenv("CORVUS_METRICS_ADJUSTMENT_RETENTION_DAYS", "365"))
ARCHIVE_BEFORE_DELETE = os.getenv("CORVUS_ARCHIVE_EVENTS", "true").lower() == "true"
ARCHIVE_DIR = Path(os.getenv("CORVUS_ARCHIVE_DIR", "/data/archive"))
CLEANUP_BATCH_SIZE = 500  # Delete in batches to avoid long locks


async def prune_events(dry_run: bool = False) -> dict[str, int]:
    """Prune events older than retention period.

    Returns dict with counts: {archived, deleted}.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=EVENT_RETENTION_DAYS)).isoformat()
    db = await get_db()
    try:
        # Count what will be pruned
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_events WHERE timestamp < ?",
            (cutoff,),
        )
        row = await cursor.fetchone()
        total = row["cnt"]

        if total == 0:
            return {"archived": 0, "deleted": 0}

        if dry_run:
            return {"archived": 0, "deleted": 0, "would_delete": total}

        archived = 0
        if ARCHIVE_BEFORE_DELETE:
            archived = await _archive_events(db, cutoff)

        # Delete in batches
        deleted = 0
        while deleted < total:
            await db.execute(
                """DELETE FROM ops_events WHERE id IN (
                    SELECT id FROM ops_events WHERE timestamp < ? LIMIT ?
                )""",
                (cutoff, CLEANUP_BATCH_SIZE),
            )
            await db.commit()
            deleted += CLEANUP_BATCH_SIZE

        # Get actual final count
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_events WHERE timestamp < ?",
            (cutoff,),
        )
        remaining = (await cursor.fetchone())["cnt"]
        actual_deleted = total - remaining

        logger.info(
            "Event cleanup: archived=%d deleted=%d (retention=%dd cutoff=%s)",
            archived,
            actual_deleted,
            EVENT_RETENTION_DAYS,
            cutoff,
        )
        return {"archived": archived, "deleted": actual_deleted}
    finally:
        await db.close()


async def prune_audit_log(dry_run: bool = False) -> dict[str, int]:
    """Prune audit log entries older than retention period."""
    cutoff = (datetime.now(UTC) - timedelta(days=AUDIT_RETENTION_DAYS)).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_audit_log WHERE timestamp < ?",
            (cutoff,),
        )
        row = await cursor.fetchone()
        total = row["cnt"]

        if total == 0 or dry_run:
            return {"deleted": 0} if total == 0 else {"would_delete": total, "deleted": 0}

        deleted = 0
        while deleted < total:
            await db.execute(
                """DELETE FROM ops_audit_log WHERE id IN (
                    SELECT id FROM ops_audit_log WHERE timestamp < ? LIMIT ?
                )""",
                (cutoff, CLEANUP_BATCH_SIZE),
            )
            await db.commit()
            deleted += CLEANUP_BATCH_SIZE

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_audit_log WHERE timestamp < ?",
            (cutoff,),
        )
        remaining = (await cursor.fetchone())["cnt"]
        actual_deleted = total - remaining

        logger.info(
            "Audit cleanup: deleted=%d (retention=%dd)",
            actual_deleted,
            AUDIT_RETENTION_DAYS,
        )
        return {"deleted": actual_deleted}
    finally:
        await db.close()


async def prune_triage_log(dry_run: bool = False) -> dict[str, int]:
    """Prune triage log entries older than retention period."""
    cutoff = (datetime.now(UTC) - timedelta(days=TRIAGE_RETENTION_DAYS)).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE timestamp < ?",
            (cutoff,),
        )
        row = await cursor.fetchone()
        total = row["cnt"]

        if total == 0 or dry_run:
            return {"deleted": 0} if total == 0 else {"would_delete": total, "deleted": 0}

        deleted = 0
        while deleted < total:
            await db.execute(
                """DELETE FROM ops_triage_log WHERE id IN (
                    SELECT id FROM ops_triage_log WHERE timestamp < ? LIMIT ?
                )""",
                (cutoff, CLEANUP_BATCH_SIZE),
            )
            await db.commit()
            deleted += CLEANUP_BATCH_SIZE

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE timestamp < ?",
            (cutoff,),
        )
        remaining = (await cursor.fetchone())["cnt"]
        actual_deleted = total - remaining

        logger.info(
            "Triage cleanup: deleted=%d (retention=%dd)",
            actual_deleted,
            TRIAGE_RETENTION_DAYS,
        )
        return {"deleted": actual_deleted}
    finally:
        await db.close()


async def prune_metrics_snapshots(dry_run: bool = False) -> dict[str, int]:
    """Prune metrics snapshots older than retention period."""
    cutoff = (datetime.now(UTC) - timedelta(days=METRICS_SNAPSHOT_RETENTION_DAYS)).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_metrics_snapshots WHERE timestamp < ?",
            (cutoff,),
        )
        total = (await cursor.fetchone())["cnt"]
        if dry_run or total == 0:
            return {"eligible": total, "deleted": 0}
        await db.execute("DELETE FROM ops_metrics_snapshots WHERE timestamp < ?", (cutoff,))
        await db.commit()
        return {"eligible": total, "deleted": total}
    finally:
        await db.close()


async def prune_metric_adjustments(dry_run: bool = False) -> dict[str, int]:
    """Prune metric adjustments older than retention period."""
    cutoff = (datetime.now(UTC) - timedelta(days=METRICS_ADJUSTMENT_RETENTION_DAYS)).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_metric_adjustments WHERE timestamp < ?",
            (cutoff,),
        )
        total = (await cursor.fetchone())["cnt"]
        if dry_run or total == 0:
            return {"eligible": total, "deleted": 0}
        await db.execute("DELETE FROM ops_metric_adjustments WHERE timestamp < ?", (cutoff,))
        await db.commit()
        return {"eligible": total, "deleted": total}
    finally:
        await db.close()


async def get_table_sizes() -> dict[str, int]:
    """Get row counts for all operational tables."""
    db = await get_db()
    try:
        tables = [
            "ops_events",
            "ops_incidents",
            "ops_changes",
            "ops_problems",
            "ops_cmdb",
            "ops_audit_log",
            "ops_triage_log",
            "ops_trust_ledger",
            "ops_metrics_snapshots",
            "ops_metric_adjustments",
        ]
        sizes: dict[str, int] = {}
        for table in tables:
            cursor = await db.execute(f"SELECT COUNT(*) as cnt FROM {table}")  # nosec B608 - Table name from allowlist
            row = await cursor.fetchone()
            sizes[table] = row["cnt"]
        return sizes
    finally:
        await db.close()


async def _archive_events(db, cutoff: str) -> int:
    """Archive events to JSONL before deletion."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_file = ARCHIVE_DIR / f"events-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.jsonl"

    cursor = await db.execute(
        "SELECT * FROM ops_events WHERE timestamp < ? ORDER BY timestamp",
        (cutoff,),
    )
    rows = await cursor.fetchall()

    count = 0
    with open(archive_file, "w") as f:
        for row in rows:
            f.write(json.dumps(dict(row)) + "\n")
            count += 1

    logger.info("Archived %d events to %s", count, archive_file)
    return count


async def run_cleanup_loop(interval_seconds: int = 86400):
    """Run cleanup once per day (default).

    Prunes events, audit log, and triage log.
    """
    while True:
        try:
            with track_task("event_cleanup") as ctx:
                events_result = await prune_events()
                audit_result = await prune_audit_log()
                triage_result = await prune_triage_log()
                snapshots_result = await prune_metrics_snapshots()
                adjustments_result = await prune_metric_adjustments()
                ctx["count"] = sum(
                    r.get("deleted", 0)
                    for r in [
                        events_result,
                        audit_result,
                        triage_result,
                        snapshots_result,
                        adjustments_result,
                    ]
                )
            logger.info(
                "Cleanup cycle complete: events=%s audit=%s triage=%s snapshots=%s adjustments=%s",
                events_result,
                audit_result,
                triage_result,
                snapshots_result,
                adjustments_result,
            )
        except Exception:
            logger.exception("Error in cleanup task")
        await asyncio.sleep(interval_seconds)
