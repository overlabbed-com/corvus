"""Problem management API endpoints."""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from src.database import get_db
from src.models.problems import (
    ProblemCorrelate,
    ProblemCreate,
    ProblemResponse,
    ProblemUpdate,
)

router = APIRouter(prefix="/ops/problems", tags=["problems"])


def _row_to_response(row) -> ProblemResponse:
    return ProblemResponse(
        id=row["id"],
        created_at=row["created_at"],
        status=row["status"],
        title=row["title"],
        pattern=row["pattern"],
        root_cause=row["root_cause"],
        recommended_fix=row["recommended_fix"],
        workaround=row["workaround"],
        correlated_incidents=json.loads(row["correlated_incidents"]),
        workstream=row["workstream"],
        severity=row["severity"],
        assigned_to=row["assigned_to"],
    )


@router.post("", response_model=ProblemResponse, status_code=201)
async def create_problem(problem: ProblemCreate):
    """Create a problem record (gap or operational)."""
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        problem_id = f"PRB-{uuid.uuid4().hex[:8].upper()}"

        await db.execute(
            """INSERT INTO ops_problems
               (id, created_at, status, title, pattern, root_cause,
                recommended_fix, workaround, severity, workstream)
               VALUES (?, ?, 'identified', ?, ?, ?, ?, ?, ?, ?)""",
            (
                problem_id,
                now,
                problem.title,
                problem.pattern,
                problem.root_cause,
                problem.recommended_fix,
                problem.workaround,
                problem.severity,
                problem.workstream,
            ),
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM ops_problems WHERE id = ?", (problem_id,))
        row = await cursor.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()


@router.get("", response_model=list[ProblemResponse])
async def list_problems(
    status: str | None = Query(None),
    pattern: str | None = Query(None),
    workstream: str | None = Query(None),
):
    """List problems with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_problems WHERE 1=1"
        params: list = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if pattern:
            query += " AND pattern LIKE ?"
            params.append(f"%{pattern}%")
        if workstream:
            query += " AND workstream = ?"
            params.append(workstream)

        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        await db.close()


@router.patch("/{problem_id}", response_model=ProblemResponse)
async def update_problem(problem_id: str, update: ProblemUpdate):
    """Update problem record."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_problems WHERE id = ?", (problem_id,))
        existing = await cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Problem not found")

        sets = []
        params: list = []

        for field in (
            "status",
            "root_cause",
            "recommended_fix",
            "workaround",
            "assigned_to",
            "workstream",
        ):
            value = getattr(update, field, None)
            if value is not None:
                sets.append(f"{field} = ?")
                params.append(value)

        if not sets:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(problem_id)
        await db.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
            f"UPDATE ops_problems SET {', '.join(sets)} WHERE id = ?",  # nosec B608  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
            params,
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM ops_problems WHERE id = ?", (problem_id,))
        row = await cursor.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()


@router.post("/correlate")
async def correlate_incident(correlation: ProblemCorrelate):
    """Correlate an incident to a problem record."""
    db = await get_db()
    try:
        # Verify both exist
        cursor = await db.execute("SELECT * FROM ops_problems WHERE id = ?", (correlation.problem_id,))
        problem = await cursor.fetchone()
        if not problem:
            raise HTTPException(status_code=404, detail="Problem not found")

        cursor = await db.execute("SELECT * FROM ops_incidents WHERE id = ?", (correlation.incident_id,))
        incident = await cursor.fetchone()
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")

        # Add incident to problem's correlated list
        incidents = json.loads(problem["correlated_incidents"])
        if correlation.incident_id not in incidents:
            incidents.append(correlation.incident_id)
            await db.execute(
                "UPDATE ops_problems SET correlated_incidents = ? WHERE id = ?",
                (json.dumps(incidents), correlation.problem_id),
            )

        # Link incident back to problem
        await db.execute(
            "UPDATE ops_incidents SET correlated_to_problem = ? WHERE id = ?",
            (correlation.problem_id, correlation.incident_id),
        )

        await db.commit()
        return {
            "status": "correlated",
            "problem_id": correlation.problem_id,
            "incident_id": correlation.incident_id,
        }
    finally:
        await db.close()
