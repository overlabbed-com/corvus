"""Runbook API endpoints — triage execution and management."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi import Query as FastQuery
from pydantic import BaseModel

from src.database import get_db
from src.runbooks.executor import execute_triage
from src.runbooks.loader import registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/runbooks", tags=["runbooks"])
triage_router = APIRouter(tags=["triage"])


class TriageRequest(BaseModel):
    target: str
    host: str = ""
    service_type: str | None = None
    investigation_data: dict[str, Any] | None = None


class TriageOutcome(BaseModel):
    outcome: Literal["success", "failure"]
    related_incident_id: str | None = None


async def _persist_triage_log(
    *,
    triage_id: str,
    timestamp: str,
    target: str,
    service_type: str,
    runbook_name: str,
    action_type: str,
    diagnosis: str | None,
    confidence: float,
    escalation_required: int,
) -> None:
    """Persist a single triage log entry (shared by normal and no-runbook paths)."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ops_triage_log
               (id, timestamp, target, service_type, runbook_name, action_type,
                diagnosis, confidence, escalation_required, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                triage_id,
                timestamp,
                target,
                service_type,
                runbook_name,
                action_type,
                diagnosis,
                confidence,
                escalation_required,
            ),
        )
        await db.commit()
    finally:
        await db.close()


@router.get("")
async def list_runbooks():
    """List all loaded runbooks."""
    return [
        {
            "name": r.name,
            "type": r.type,
            "service_type": r.service_type,
            "version": r.version,
            "description": r.description,
            "investigation_steps": len(r.investigation),
            "diagnosis_hints": len(r.diagnosis_hints),
        }
        for r in registry.list_all()
    ]


@router.get("/coverage")
async def runbook_coverage():
    """Show which service types have runbook coverage."""
    covered = registry.service_types_covered
    return {
        "covered_service_types": sorted(covered),
        "total_runbooks": len(registry.list_all()),
    }


@router.post("/triage")
async def run_triage(request: TriageRequest):
    """Execute triage for a target using the matching runbook.

    Selects runbook by service_type and runs investigation + diagnosis.
    """
    service_type = request.service_type

    # If service_type not provided, look up from CMDB
    if not service_type:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT service_type FROM ops_cmdb WHERE name = ?",
                (request.target,),
            )
            row = await cursor.fetchone()
            if row:
                service_type = row["service_type"]
        finally:
            await db.close()

    if not service_type:
        raise HTTPException(
            status_code=400,
            detail=f"No service_type for target '{request.target}'. Register in CMDB first.",
        )

    runbook = registry.get_for_service_type(service_type)
    if not runbook:
        # Still log the triage attempt even with no runbook
        triage_id = f"TRG-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(UTC).isoformat()
        action_type = f"no_runbook:{service_type}"

        await _persist_triage_log(
            triage_id=triage_id,
            timestamp=now,
            target=request.target,
            service_type=service_type,
            runbook_name="none",
            action_type=action_type,
            diagnosis=None,
            confidence=0.0,
            escalation_required=0,
        )

        return {
            "status": "no_runbook",
            "triage_id": triage_id,
            "target": request.target,
            "service_type": service_type,
            "message": f"No runbook for service_type '{service_type}'. Gap recorded.",
            "gap_pattern": f"gap:coverage:no-runbook:{service_type}",
        }

    result = await execute_triage(
        runbook=runbook,
        target=request.target,
        host=request.host,
        investigation_data=request.investigation_data,
    )

    triage_id = f"TRG-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(UTC).isoformat()
    action_type = f"{result.diagnosis or 'unknown'}:{service_type}"

    await _persist_triage_log(
        triage_id=triage_id,
        timestamp=now,
        target=request.target,
        service_type=service_type,
        runbook_name=runbook.name,
        action_type=action_type,
        diagnosis=result.diagnosis,
        confidence=result.confidence,
        escalation_required=1 if result.escalation_required else 0,
    )

    return {
        "status": "triaged",
        "triage_id": triage_id,
        "target": request.target,
        "service_type": service_type,
        **result.to_dict(),
    }


@triage_router.get("/ops/triage")
async def list_triage(
    service_type: str | None = FastQuery(None),
    runbook_name: str | None = FastQuery(None),
    outcome: str | None = FastQuery(None),
    limit: int = FastQuery(100, le=1000),
):
    """List triage log entries with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_triage_log WHERE 1=1"
        params: list = []
        if service_type:
            query += " AND service_type = ?"
            params.append(service_type)
        if runbook_name:
            query += " AND runbook_name = ?"
            params.append(runbook_name)
        if outcome:
            query += " AND outcome = ?"
            params.append(outcome)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@triage_router.patch("/ops/triage/{triage_id}")
async def record_triage_outcome(triage_id: str, outcome_req: TriageOutcome):
    """Record the outcome of a triage execution."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_triage_log WHERE id = ?", (triage_id,))
        entry = await cursor.fetchone()
        if not entry:
            raise HTTPException(status_code=404, detail="Triage entry not found")

        if entry["outcome"] != "pending":
            raise HTTPException(status_code=409, detail="Outcome already recorded")

        now = datetime.now(UTC)
        created = datetime.fromisoformat(entry["timestamp"])
        minutes = int((now - created).total_seconds() / 60)

        sets = ["outcome = ?", "outcome_at = ?", "resolution_time_minutes = ?"]
        params: list = [outcome_req.outcome, now.isoformat(), minutes]

        if outcome_req.related_incident_id:
            sets.append("related_incident_id = ?")
            params.append(outcome_req.related_incident_id)

        params.append(triage_id)
        await db.execute(
            f"UPDATE ops_triage_log SET {', '.join(sets)} WHERE id = ?",  # nosec B608 - Dynamic SQL uses allowlist
            params,
        )
        await db.commit()

        # Auto-index triage result into knowledge base
        try:
            from src.routers.knowledge import index_triage_result

            await index_triage_result(triage_id)
        except Exception:
            logger.exception("Knowledge indexing failed for triage %s", triage_id)

        cursor = await db.execute("SELECT * FROM ops_triage_log WHERE id = ?", (triage_id,))
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()
