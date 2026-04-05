"""Change window API endpoints."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from src.config import CHANGE_EXPIRY_HOURS
from src.database import get_db
from src.models.changes import ChangeCreate, ChangeResponse, ChangeUpdate

router = APIRouter(prefix="/ops/changes", tags=["changes"])


def _row_to_response(row) -> ChangeResponse:
    return ChangeResponse(
        id=row["id"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        status=row["status"],
        targets=json.loads(row["targets"]),
        description=row["description"],
        rollback_plan=row["rollback_plan"],
        project=row["project"],
        auto_expire=bool(row["auto_expire"]),
        expires_at=row["expires_at"],
        completed_at=row["completed_at"],
        outcome=row["outcome"],
        authenticated_as=row["authenticated_as"],
    )


@router.post("", response_model=ChangeResponse, status_code=201)
async def create_change(change: ChangeCreate, request: Request):
    """Create a new change window."""
    # Record authenticated identity (S1.2 — prevents agent impersonation)
    authenticated_as = "anonymous"
    if hasattr(request.state, "auth"):
        authenticated_as = request.state.auth.identity

    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        change_id = f"CHG-{uuid.uuid4().hex[:8].upper()}"
        expires_at = None
        if change.auto_expire:
            expires_at = (datetime.now(UTC) + timedelta(hours=CHANGE_EXPIRY_HOURS)).isoformat()

        await db.execute(
            """INSERT INTO ops_changes
               (id, created_at, created_by, status, targets, description,
                rollback_plan, project, auto_expire, expires_at, authenticated_as)
               VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)""",
            (
                change_id,
                now,
                change.created_by,
                json.dumps(change.targets),
                change.description,
                change.rollback_plan,
                change.project,
                1 if change.auto_expire else 0,
                expires_at,
                authenticated_as,
            ),
        )
        await db.commit()

        row = await db.execute("SELECT * FROM ops_changes WHERE id = ?", (change_id,))
        row = await row.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()


@router.get("", response_model=list[ChangeResponse])
async def list_changes(
    status: str | None = Query(None),
    target: str | None = Query(None),
    created_by: str | None = Query(None),
):
    """List change windows with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_changes WHERE 1=1"
        params: list = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if target:
            query += " AND targets LIKE ?"
            params.append(f"%{target}%")
        if created_by:
            query += " AND created_by = ?"
            params.append(created_by)

        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        await db.close()


@router.get("/active", response_model=list[ChangeResponse])
async def list_active_changes():
    """List only active change windows."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_changes WHERE status = 'active' ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        await db.close()


@router.patch("/{change_id}", response_model=ChangeResponse)
async def update_change(change_id: str, update: ChangeUpdate):
    """Update a change window (status, outcome). Targets are immutable."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_changes WHERE id = ?", (change_id,))
        existing = await cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Change not found")

        sets = []
        params: list = []

        if update.status is not None:
            sets.append("status = ?")
            params.append(update.status)
            if update.status in ("completed", "failed"):
                sets.append("completed_at = ?")
                params.append(datetime.now(UTC).isoformat())

        if update.outcome is not None:
            sets.append("outcome = ?")
            params.append(update.outcome)

        if not sets:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(change_id)
        await db.execute(
            f"UPDATE ops_changes SET {', '.join(sets)} WHERE id = ?",  # nosec B608 - Dynamic SQL uses allowlist
            params,
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM ops_changes WHERE id = ?", (change_id,))
        row = await cursor.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()
