"""Trust ledger — tracks action-type success rates and manages trust tiers.

Agents earn trust through demonstrated competence:
  ESCALATE -> SUPERVISED -> AUTO

Promotion: >95% success rate over 20+ executions -> advance one tier.
Demotion: Any failure at AUTO -> back to SUPERVISED.
"""

from datetime import UTC, datetime
from typing import Any

from src.database import get_db

TIER_ESCALATE = "ESCALATE"
TIER_SUPERVISED = "SUPERVISED"
TIER_AUTO = "AUTO"

TIER_ORDER = [TIER_ESCALATE, TIER_SUPERVISED, TIER_AUTO]

PROMOTION_THRESHOLD = 0.95  # 95% success rate
PROMOTION_MIN_COUNT = 20  # minimum executions before promotion


async def record_outcome(action_type: str, outcome: str) -> dict[str, Any]:
    """Record a triage outcome and evaluate promotion/demotion.

    Args:
        action_type: e.g., "remediation.restart:inference"
        outcome: "success" or "failure"

    Returns:
        Updated trust ledger entry.
    """
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()

        # Atomic upsert: create entry if not exists
        await db.execute(
            """INSERT OR IGNORE INTO ops_trust_ledger
               (action_type, total_count, success_count, failure_count, trust_tier)
               VALUES (?, 0, 0, 0, ?)""",
            (action_type, TIER_ESCALATE),
        )

        # Increment counters
        if outcome == "success":
            await db.execute(
                """UPDATE ops_trust_ledger
                   SET total_count = total_count + 1,
                       success_count = success_count + 1
                   WHERE action_type = ?""",
                (action_type,),
            )
        else:
            await db.execute(
                """UPDATE ops_trust_ledger
                   SET total_count = total_count + 1,
                       failure_count = failure_count + 1
                   WHERE action_type = ?""",
                (action_type,),
            )

        # Re-read current state
        cursor = await db.execute(
            "SELECT * FROM ops_trust_ledger WHERE action_type = ?",
            (action_type,),
        )
        current = await cursor.fetchone()
        current_tier = current["trust_tier"]
        total = current["total_count"]
        successes = current["success_count"]

        # Evaluate demotion first (takes priority)
        if current_tier == TIER_AUTO and outcome == "failure":
            await db.execute(
                "UPDATE ops_trust_ledger SET trust_tier = ?, demoted_at = ? WHERE action_type = ?",
                (TIER_SUPERVISED, now, action_type),
            )
        # Evaluate promotion (only on success outcomes)
        elif outcome == "success" and total >= PROMOTION_MIN_COUNT:
            success_rate = successes / total
            if success_rate >= PROMOTION_THRESHOLD:
                tier_idx = TIER_ORDER.index(current_tier)
                if tier_idx < len(TIER_ORDER) - 1:
                    new_tier = TIER_ORDER[tier_idx + 1]
                    await db.execute(
                        "UPDATE ops_trust_ledger SET trust_tier = ?, promoted_at = ?, "
                        "total_count = 0, success_count = 0, failure_count = 0 "
                        "WHERE action_type = ?",
                        (new_tier, now, action_type),
                    )

        await db.commit()

        # Return final state
        cursor = await db.execute(
            "SELECT * FROM ops_trust_ledger WHERE action_type = ?",
            (action_type,),
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


async def get_trust_tier(action_type: str) -> dict[str, Any]:
    """Get the trust tier for an action type.

    Returns a dict with tier info, or defaults for unknown action types.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ops_trust_ledger WHERE action_type = ?",
            (action_type,),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return {
            "action_type": action_type,
            "total_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "trust_tier": TIER_ESCALATE,
            "promoted_at": None,
            "demoted_at": None,
        }
    finally:
        await db.close()


async def run_promotion_sweep() -> dict[str, Any]:
    """Bulk-evaluate all action types for promotion.

    Checks every entry in the trust ledger against promotion criteria
    (>95% success rate, 20+ executions) and promotes eligible entries.

    Returns:
        Dict with promoted action types and counts.
    """
    db = await get_db()
    promoted: list[dict[str, str]] = []
    try:
        now = datetime.now(UTC).isoformat()
        cursor = await db.execute("SELECT * FROM ops_trust_ledger WHERE trust_tier != ?", (TIER_AUTO,))
        entries = await cursor.fetchall()

        for entry in entries:
            total = entry["total_count"]
            successes = entry["success_count"]
            current_tier = entry["trust_tier"]

            if total < PROMOTION_MIN_COUNT:
                continue

            success_rate = successes / total
            if success_rate < PROMOTION_THRESHOLD:
                continue

            tier_idx = TIER_ORDER.index(current_tier)
            if tier_idx >= len(TIER_ORDER) - 1:
                continue

            new_tier = TIER_ORDER[tier_idx + 1]
            await db.execute(
                "UPDATE ops_trust_ledger SET trust_tier = ?, promoted_at = ?, "
                "total_count = 0, success_count = 0, failure_count = 0 "
                "WHERE action_type = ?",
                (new_tier, now, entry["action_type"]),
            )
            promoted.append(
                {
                    "action_type": entry["action_type"],
                    "from_tier": current_tier,
                    "to_tier": new_tier,
                    "success_rate": round(success_rate * 100, 1),
                }
            )

        await db.commit()
        return {
            "evaluated": len(entries),
            "promoted": len(promoted),
            "promotions": promoted,
        }
    finally:
        await db.close()


async def get_all_tiers() -> list[dict[str, Any]]:
    """Get the full trust ledger."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_trust_ledger ORDER BY trust_tier, action_type")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
