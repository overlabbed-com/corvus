"""Pattern quality API endpoints.

Track and score triage patterns for quality and accuracy.
"""

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from src.database import get_db
from src.models.patterns import Pattern, PatternFeedback, PatternMetrics, PatternQualityResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/patterns", tags=["patterns"])


@router.get("")
async def list_patterns(
    pattern_type: str = Query(None),
    min_quality: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=1000),
):
    """List all patterns with quality scores."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_patterns WHERE 1=1"
        params = []

        if pattern_type:
            query += " AND pattern_type = ?"
            params.append(pattern_type)

        query += " ORDER BY quality_score DESC LIMIT ?"
        params.append(limit)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        patterns = []
        for row in rows:
            pattern = Pattern(
                id=row["id"],
                name=row["name"],
                pattern_type=row["pattern_type"],
                source=row["source"],
                trigger_conditions=json.loads(row["trigger_conditions"]) if row["trigger_conditions"] else {},
                diagnosis=row["diagnosis"],
                avg_confidence=row["avg_confidence"],
                usage_count=row["usage_count"],
                success_count=row["success_count"],
                last_used_at=row["last_used_at"],
                quality_score=row["quality_score"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

            accuracy = row["success_count"] / row["usage_count"] if row["usage_count"] > 0 else 0.0
            failure_count = row["usage_count"] - row["success_count"]

            metrics = PatternMetrics(
                pattern_id=pattern.id,
                name=pattern.name,
                accuracy=accuracy,
                usage_count=pattern.usage_count,
                success_count=pattern.success_count,
                failure_count=failure_count,
                quality_score=pattern.quality_score,
                last_used_at=pattern.last_used_at,
            )

            patterns.append(PatternQualityResponse(pattern=pattern, metrics=metrics))

        return patterns
    finally:
        await db.close()


@router.get("/bottom-10")
async def get_bottom_patterns(limit: int = Query(10, ge=1, le=50)):
    """Get lowest quality patterns."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM ops_patterns
               WHERE usage_count >= 3
               ORDER BY quality_score ASC, usage_count DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()

        patterns = []
        for row in rows:
            accuracy = row["success_count"] / row["usage_count"] if row["usage_count"] > 0 else 0.0
            patterns.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "quality_score": row["quality_score"],
                    "accuracy": accuracy,
                    "usage_count": row["usage_count"],
                    "diagnosis": row["diagnosis"],
                }
            )

        return patterns
    finally:
        await db.close()


@router.get("/top-10")
async def get_top_patterns(limit: int = Query(10, ge=1, le=50)):
    """Get highest quality patterns."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM ops_patterns
               WHERE usage_count >= 3
               ORDER BY quality_score DESC, usage_count DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()

        patterns = []
        for row in rows:
            accuracy = row["success_count"] / row["usage_count"] if row["usage_count"] > 0 else 0.0
            patterns.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "quality_score": row["quality_score"],
                    "accuracy": accuracy,
                    "usage_count": row["usage_count"],
                    "diagnosis": row["diagnosis"],
                }
            )

        return patterns
    finally:
        await db.close()


@router.get("/{pattern_id}")
async def get_pattern(pattern_id: str):
    """Get pattern details with metrics."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_patterns WHERE id = ?", (pattern_id,))
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Pattern not found")

        pattern = Pattern(
            id=row["id"],
            name=row["name"],
            pattern_type=row["pattern_type"],
            source=row["source"],
            trigger_conditions=json.loads(row["trigger_conditions"]) if row["trigger_conditions"] else {},
            diagnosis=row["diagnosis"],
            avg_confidence=row["avg_confidence"],
            usage_count=row["usage_count"],
            success_count=row["success_count"],
            last_used_at=row["last_used_at"],
            quality_score=row["quality_score"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

        accuracy = row["success_count"] / row["usage_count"] if row["usage_count"] > 0 else 0.0
        failure_count = row["usage_count"] - row["success_count"]

        metrics = PatternMetrics(
            pattern_id=pattern.id,
            name=pattern.name,
            accuracy=accuracy,
            usage_count=pattern.usage_count,
            success_count=pattern.success_count,
            failure_count=failure_count,
            quality_score=pattern.quality_score,
            last_used_at=pattern.last_used_at,
        )

        return PatternQualityResponse(pattern=pattern, metrics=metrics)
    finally:
        await db.close()


@router.post("/{pattern_id}/feedback")
async def submit_feedback(pattern_id: str, feedback: PatternFeedback):
    """Submit feedback on pattern outcome."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_patterns WHERE id = ?", (pattern_id,))
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Pattern not found")

        now = datetime.now(UTC).isoformat()
        success = 1 if feedback.success else 0

        await db.execute(
            """UPDATE ops_patterns SET
               usage_count = usage_count + 1,
               success_count = success_count + ?,
               last_used_at = ?,
               updated_at = ?
               WHERE id = ?""",
            (success, now, now, pattern_id),
        )

        await db.execute(
            """INSERT INTO ops_pattern_feedback
               (pattern_id, success, resolution_time_minutes, notes, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (pattern_id, success, feedback.resolution_time_minutes, feedback.notes, now),
        )

        cursor = await db.execute("SELECT usage_count, success_count FROM ops_patterns WHERE id = ?", (pattern_id,))
        updated = await cursor.fetchone()

        if updated and updated["usage_count"] > 0:
            new_accuracy = updated["success_count"] / updated["usage_count"]
            await db.execute(
                "UPDATE ops_patterns SET quality_score = ?, updated_at = ? WHERE id = ?",
                (new_accuracy, now, pattern_id),
            )

        await db.commit()

        return {"status": "success", "pattern_id": pattern_id}
    finally:
        await db.close()
