"""Incident API endpoints."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request

from src.database import get_db
from src.models.incidents import IncidentCreate, IncidentResponse, IncidentUpdate
from src.sanitizer import sanitize

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ops/incidents", tags=["incidents"])


def _row_to_response(row) -> IncidentResponse:
    return IncidentResponse(
        id=row["id"],
        created_at=row["created_at"],
        detected_by=row["detected_by"],
        target=row["target"],
        status=row["status"],
        severity=row["severity"],
        title=row["title"],
        description=row["description"],
        root_cause=row["root_cause"],
        investigation_summary=row["investigation_summary"],
        remediation_applied=row["remediation_applied"],
        resolved_at=row["resolved_at"],
        resolution_time_minutes=row["resolution_time_minutes"],
        correlated_to_problem=row["correlated_to_problem"],
        authenticated_as=row["authenticated_as"],
    )


@router.post("", response_model=IncidentResponse, status_code=201)
async def create_incident(incident: IncidentCreate, request: Request):
    """Create a new incident record."""
    # Record authenticated identity (S1.2 — prevents agent impersonation)
    authenticated_as = "anonymous"
    if hasattr(request.state, "auth"):
        authenticated_as = request.state.auth.identity

    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"

        await db.execute(
            """INSERT INTO ops_incidents
               (id, created_at, detected_by, target, status, severity, title, description, authenticated_as)
               VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
            (
                incident_id,
                now,
                incident.detected_by,
                incident.target,
                incident.severity,
                sanitize(incident.title),
                sanitize(incident.description),
                authenticated_as,
            ),
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM ops_incidents WHERE id = ?", (incident_id,))
        row = await cursor.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()


@router.get("", response_model=list[IncidentResponse])
async def list_incidents(
    status: str | None = Query(None),
    target: str | None = Query(None),
    severity: str | None = Query(None),
):
    """List incidents with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_incidents WHERE 1=1"
        params: list = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if target:
            query += " AND target = ?"
            params.append(target)
        if severity:
            query += " AND severity = ?"
            params.append(severity)

        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        await db.close()


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str):
    """Get incident with full context."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_incidents WHERE id = ?", (incident_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Incident not found")
        return _row_to_response(row)
    finally:
        await db.close()


@router.patch("/{incident_id}", response_model=IncidentResponse)
async def update_incident(incident_id: str, update: IncidentUpdate):
    """Update incident status, investigation notes, etc."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_incidents WHERE id = ?", (incident_id,))
        existing = await cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Incident not found")

        sets = []
        params: list = []

        # Fields that may contain log excerpts with secrets
        _sanitize_fields = {"root_cause", "investigation_summary", "remediation_applied"}

        for field in (
            "status",
            "severity",
            "root_cause",
            "investigation_summary",
            "remediation_applied",
            "correlated_to_problem",
        ):
            value = getattr(update, field, None)
            if value is not None:
                if field in _sanitize_fields:
                    value = sanitize(value)
                sets.append(f"{field} = ?")
                params.append(value)

        if update.status == "investigating" and not existing["investigating_at"]:
            sets.append("investigating_at = ?")
            params.append(datetime.now(UTC).isoformat())

        if update.status == "resolved":
            now = datetime.now(UTC).isoformat()
            sets.append("resolved_at = ?")
            params.append(now)
            created = datetime.fromisoformat(existing["created_at"])
            resolved = datetime.fromisoformat(now)
            minutes = int((resolved - created).total_seconds() / 60)
            sets.append("resolution_time_minutes = ?")
            params.append(minutes)

        if not sets:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(incident_id)
        await db.execute(
            f"UPDATE ops_incidents SET {', '.join(sets)} WHERE id = ?",  # nosec B608 - Dynamic SQL uses allowlist
            params,
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM ops_incidents WHERE id = ?", (incident_id,))
        row = await cursor.fetchone()
        response = _row_to_response(row)

        # Trigger gap detection on resolution
        if update.status == "resolved":
            try:
                from src.tasks.gap_detection import check_incident_gaps

                await check_incident_gaps(incident_id)
            except Exception:
                logger.exception("Gap detection failed for %s", incident_id)

            # Auto-index resolved incident into knowledge base
            try:
                from src.routers.knowledge import index_resolved_incident

                await index_resolved_incident(incident_id)
            except Exception:
                logger.exception("Knowledge indexing failed for %s", incident_id)

        return response
    finally:
        await db.close()
