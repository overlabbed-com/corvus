"""Story 5.1: WAL checkpoint configuration.

Configure SQLite WAL auto-checkpoint to prevent WAL file bloat.
"""

import logging

logger = logging.getLogger(__name__)


async def configure_wal_checkpoint():
    """Configure WAL auto-checkpoint to prevent file bloat.
    
    Story 5.1: Long-running transactions could cause WAL file bloat.
    Set auto-checkpoint to 1000 pages (~8MB) to prevent this.
    """
    from src.database import get_db
    
    try:
        db = await get_db()
        try:
            # Set auto-checkpoint to 1000 pages (1000 * 4KB = ~4MB)
            await db.execute("PRAGMA wal_autocheckpoint=1000")
            logger.info("WAL auto-checkpoint configured to 1000 pages")
        finally:
            await db.close()
    except Exception as e:
        logger.warning(f"Failed to configure WAL checkpoint: {e}")


async def checkpoint_wal():
    """Manually checkpoint the WAL file.
    
    Can be called periodically or when disk space is low.
    """
    from src.database import get_db
    
    try:
        db = await get_db()
        try:
            await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint completed")
        finally:
            await db.close()
    except Exception as e:
        logger.warning(f"Failed to checkpoint WAL: {e}")
