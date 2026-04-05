"""Step execution endpoints — agent-side runbook step protocol.

Agents pull pending steps, execute them (SSH, Docker API, etc.),
and report results back. The server continues triage once all
steps for a triage run are complete.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi import Query as FastQuery
from pydantic import BaseModel

from src.database import get_db

router = APIRouter(prefix="/ops/runbooks/steps", tags=["steps"])


class StepResultRequest(BaseModel):
    output: Any = None
    error: str | None = None
    success: bool = True


class AsyncTriageRequest(BaseModel):
    target: str
    host: str = ""
    service_type: str | None = None
    investigation_data: dict[str, Any] | None = None
    agent: str = "mcp-agent"


async def create_pending_steps(
    triage_id: str,
    steps: list[dict[str, Any]],
    context: dict[str, str],
) -> list[dict[str, Any]]:
    """Create pending step records for a triage run.

    Returns list of step dicts with IDs for agent consumption.
    """
    db = await get_db()
    try:
        created = []
        now = datetime.now(UTC).isoformat()
        for step in steps:
            step_id = f"STEP-{uuid.uuid4().hex[:8].upper()}"
            step_type = step.get("type", "unknown")
            params = step.get("params", {})
            timeout = step.get("timeout", 30)

            # Template substitution on params
            resolved_params = {}
            for key, value in params.items():
                if isinstance(value, str):
                    for ctx_key, ctx_val in context.items():
                        value = value.replace(f"{{{{ {ctx_key} }}}}", ctx_val)
                        value = value.replace(f"{{{{{ctx_key}}}}}", ctx_val)
                resolved_params[key] = value

            import json

            await db.execute(
                """INSERT INTO ops_pending_steps
                   (id, triage_id, step_name, step_type, params, timeout, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    step_id,
                    triage_id,
                    step.get("name", "unnamed"),
                    step_type,
                    json.dumps(resolved_params),
                    timeout,
                    now,
                ),
            )
            created.append(
                {
                    "step_id": step_id,
                    "step_name": step.get("name", "unnamed"),
                    "step_type": step_type,
                    "params": resolved_params,
                    "timeout": timeout,
                }
            )

        await db.commit()
        return created
    finally:
        await db.close()


@router.get("/pending")
async def list_pending_steps(
    triage_id: str | None = FastQuery(None, description="Filter by triage ID"),
    limit: int = FastQuery(50, le=500),
):
    """List pending steps waiting for agent execution."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_pending_steps WHERE status = 'pending'"
        params: list = []
        if triage_id:
            query += " AND triage_id = ?"
            params.append(triage_id)
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        import json

        for r in rows:
            row_dict = dict(r)
            row_dict["params"] = json.loads(row_dict["params"]) if row_dict["params"] else {}
            results.append(row_dict)
        return results
    finally:
        await db.close()


@router.post("/{step_id}/result")
async def submit_step_result(step_id: str, result_req: StepResultRequest):
    """Agent reports the result of executing a step."""
    import json

    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_pending_steps WHERE id = ?", (step_id,))
        step = await cursor.fetchone()
        if not step:
            raise HTTPException(status_code=404, detail="Step not found")

        if step["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Step already {step['status']}",
            )

        now = datetime.now(UTC).isoformat()
        new_status = "completed" if result_req.success else "failed"

        await db.execute(
            """UPDATE ops_pending_steps
               SET status = ?, output = ?, error = ?, completed_at = ?
               WHERE id = ?""",
            (
                new_status,
                json.dumps(result_req.output) if result_req.output is not None else None,
                result_req.error,
                now,
                step_id,
            ),
        )
        await db.commit()

        # Check if all steps for this triage are done
        cursor = await db.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending
               FROM ops_pending_steps WHERE triage_id = ?""",
            (step["triage_id"],),
        )
        counts = await cursor.fetchone()
        all_done = counts["pending"] == 0

        return {
            "step_id": step_id,
            "status": new_status,
            "triage_id": step["triage_id"],
            "all_steps_complete": all_done,
            "total_steps": counts["total"],
            "pending_steps": counts["pending"],
        }
    finally:
        await db.close()


@router.get("/{step_id}")
async def get_step(step_id: str):
    """Get a single step's details and status."""
    import json

    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_pending_steps WHERE id = ?", (step_id,))
        step = await cursor.fetchone()
        if not step:
            raise HTTPException(status_code=404, detail="Step not found")
        row_dict = dict(step)
        row_dict["params"] = json.loads(row_dict["params"]) if row_dict["params"] else {}
        if row_dict["output"]:
            row_dict["output"] = json.loads(row_dict["output"])
        return row_dict
    finally:
        await db.close()


@router.post("/triage/async")
async def start_async_triage(request: AsyncTriageRequest):
    """Start an async triage — returns pending steps for agent execution.

    Unlike the synchronous triage endpoint, this returns immediately with
    a list of steps the agent needs to execute. The agent executes each step
    and reports results via POST /steps/{step_id}/result. Once all steps are
    complete, call POST /steps/triage/{triage_id}/continue to get the diagnosis.
    """
    from src.runbooks.loader import registry

    service_type = request.service_type

    # Look up service_type from CMDB if not provided
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
        raise HTTPException(
            status_code=404,
            detail=f"No runbook for service_type '{service_type}'.",
        )

    triage_id = f"TRG-{uuid.uuid4().hex[:8].upper()}"
    context = {"target": request.target, "host": request.host}

    # Identify which steps need agent execution (noop steps)
    from src.runbooks.executor import STEP_HANDLERS, _noop_step

    agent_steps = []
    server_steps = []
    for step in runbook.investigation:
        step_type = step.get("type", "unknown")
        handler = STEP_HANDLERS.get(step_type)
        if handler is _noop_step or handler is None:
            agent_steps.append(step)
        else:
            server_steps.append(step)

    # Create pending step records for agent steps
    pending = await create_pending_steps(triage_id, agent_steps, context)

    # Store triage metadata for later continuation

    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """INSERT INTO ops_triage_log
               (id, timestamp, target, service_type, runbook_name, action_type,
                diagnosis, confidence, escalation_required, outcome)
               VALUES (?, ?, ?, ?, ?, ?, NULL, 0.0, 0, 'awaiting_steps')""",
            (
                triage_id,
                now,
                request.target,
                service_type,
                runbook.name,
                f"async_triage:{service_type}",
            ),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "status": "awaiting_steps",
        "triage_id": triage_id,
        "target": request.target,
        "service_type": service_type,
        "runbook_name": runbook.name,
        "pending_steps": pending,
        "total_steps": len(agent_steps),
        "server_steps": len(server_steps),
    }


@router.post("/triage/{triage_id}/continue")
async def continue_triage(triage_id: str):
    """Continue triage after agent has submitted all step results.

    Collects step outputs, runs diagnosis matching, and returns the result.
    """
    import json

    db = await get_db()
    try:
        # Verify triage exists and is awaiting steps
        cursor = await db.execute("SELECT * FROM ops_triage_log WHERE id = ?", (triage_id,))
        triage = await cursor.fetchone()
        if not triage:
            raise HTTPException(status_code=404, detail="Triage not found")

        if triage["outcome"] not in ("awaiting_steps", "pending"):
            raise HTTPException(
                status_code=409,
                detail=f"Triage outcome is '{triage['outcome']}', not awaiting_steps",
            )

        # Check all steps are done
        cursor = await db.execute(
            """SELECT * FROM ops_pending_steps
               WHERE triage_id = ? ORDER BY created_at ASC""",
            (triage_id,),
        )
        steps = await cursor.fetchall()

        pending_count = sum(1 for s in steps if s["status"] == "pending")
        if pending_count > 0:
            return {
                "status": "still_waiting",
                "triage_id": triage_id,
                "pending_steps": pending_count,
                "total_steps": len(steps),
            }

        # Collect step outputs into investigation_data
        investigation_data: dict[str, Any] = {}
        for step in steps:
            output = json.loads(step["output"]) if step["output"] else None
            investigation_data[step["step_name"]] = {
                "type": step["step_type"],
                "success": step["status"] == "completed",
                "output": output,
                "error": step["error"],
            }
    finally:
        await db.close()

    # Now run the diagnosis with collected data
    from src.runbooks.executor import execute_triage
    from src.runbooks.loader import registry

    runbook = registry.get_for_service_type(triage["service_type"])
    if not runbook:
        raise HTTPException(
            status_code=500,
            detail=f"Runbook for '{triage['service_type']}' no longer available",
        )

    result = await execute_triage(
        runbook=runbook,
        target=triage["target"],
        host="",
        investigation_data=investigation_data,
    )

    # Update the triage log with diagnosis
    db = await get_db()
    try:
        now = datetime.now(UTC)
        created = datetime.fromisoformat(triage["timestamp"])
        minutes = int((now - created).total_seconds() / 60)

        await db.execute(
            """UPDATE ops_triage_log
               SET diagnosis = ?, confidence = ?, escalation_required = ?,
                   outcome = 'pending', resolution_time_minutes = ?
               WHERE id = ?""",
            (
                result.diagnosis,
                result.confidence,
                1 if result.escalation_required else 0,
                minutes,
                triage_id,
            ),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "status": "triaged",
        "triage_id": triage_id,
        "target": triage["target"],
        "service_type": triage["service_type"],
        **result.to_dict(),
    }
