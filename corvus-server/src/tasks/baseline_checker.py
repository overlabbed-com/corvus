"""Pre-incident baseline filter.

Checks CMDB baseline_behavior before creating incidents.
If the event matches expected behavior, it's not an incident.
"""

import json
import logging

from src.database import get_db

logger = logging.getLogger(__name__)


async def check_baseline(target: str, event_type: str) -> bool:
    """Return True if this event matches the target's expected baseline behavior.

    True means 'this is normal, not an incident.'

    Logic:
    - Look up the target in CMDB.
    - Parse its baseline_behavior JSON.
    - Check if event_type is in the expected_events list.
    - If the target is not in CMDB or has no baseline, return False (unknown = not normal).
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT baseline_behavior FROM ops_cmdb WHERE name = ?",
            (target,),
        )
        row = await cursor.fetchone()

        if not row:
            logger.debug("Target %s not found in CMDB, treating as unexpected", target)
            return False

        baseline_raw = row["baseline_behavior"]
        if not baseline_raw or baseline_raw == "{}":
            return False

        baseline = json.loads(baseline_raw)
        expected_events = baseline.get("expected_events", [])

        if event_type in expected_events:
            logger.debug("Event %s is expected baseline for %s", event_type, target)
            return True

        return False
    finally:
        await db.close()
