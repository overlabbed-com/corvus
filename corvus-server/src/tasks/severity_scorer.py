"""Intelligent severity scoring based on CMDB context.

Simplified interface for Issue #5 signal quality.
"""

import json
import logging

from src.database import get_db

logger = logging.getLogger(__name__)


async def score_severity(target: str) -> str:
    """Score severity based on service_type, critical flag, and dependency count.

    Returns:
        "high"   — critical=True AND len(dependencies) >= 3
        "medium" — critical=True (but fewer deps), OR default for unknown/uncategorized
        "low"    — service_type in ("utility", "media") and not critical
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT service_type, critical, dependencies FROM ops_cmdb WHERE name = ?",
            (target,),
        )
        row = await cursor.fetchone()

        if not row:
            return "medium"

        is_critical = bool(row["critical"])
        deps = json.loads(row["dependencies"]) if row["dependencies"] else []
        service_type = row["service_type"] or ""

        if is_critical and len(deps) >= 3:
            return "high"

        if is_critical:
            return "medium"

        if service_type in ("utility", "media") and not is_critical:
            return "low"

        return "medium"
    finally:
        await db.close()
