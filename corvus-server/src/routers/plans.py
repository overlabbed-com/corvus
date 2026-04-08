"""Plan execution API endpoints — CRUD for multi-step operational plans."""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from src.database import get_db
from src.models.plans import PlanCreate, PlanResponse, PlanStepResponse

router = APIRouter(prefix="/ops/plans", tags=["plans"])

VALID_FAILURE_POLICIES = {"halt", "skip", "retry"}
CANCELLABLE_STATUSES = {"draft", "approved", "blocked"}


def _step_row_to_response(row) -> PlanStepResponse:
    return PlanStepResponse(
        id=row["id"],
        plan_id=row["plan_id"],
        name=row["name"],
        description=row["description"],
        sequence=row["sequence"],
        depends_on=json.loads(row["depends_on"]),
        action_type=row["action_type"],
        targets=json.loads(row["targets"]),
        params=json.loads(row["params"]),
        failure_policy=row["failure_policy"],
        max_retries=row["max_retries"],
        rollback=json.loads(row["rollback"]) if row["rollback"] else None,
        timeout=row["timeout"],
        status=row["status"],
        output=json.loads(row["output"]) if row["output"] else None,
        error=row["error"],
        executed_by=row["executed_by"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        retry_count=row["retry_count"],
    )


def _plan_row_to_response(row, steps: list[PlanStepResponse] | None = None) -> PlanResponse:
    return PlanResponse(
        id=row["id"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        targets=json.loads(row["targets"]),
        change_id=row["change_id"],
        approval_method=row["approval_method"],
        approved_at=row["approved_at"],
        approved_by=row["approved_by"],
        completed_at=row["completed_at"],
        outcome=row["outcome"],
        expires_hours=row["expires_hours"],
        steps=steps or [],
    )


async def _fetch_plan_with_steps(db, plan_id: str) -> PlanResponse:
    """Fetch a plan and its steps, return as PlanResponse."""
    cursor = await db.execute("SELECT * FROM ops_plans WHERE id = ?", (plan_id,))
    plan_row = await cursor.fetchone()
    if not plan_row:
        raise HTTPException(status_code=404, detail="Plan not found")

    cursor = await db.execute(
        "SELECT * FROM ops_plan_steps WHERE plan_id = ? ORDER BY sequence ASC",
        (plan_id,),
    )
    step_rows = await cursor.fetchall()
    steps = [_step_row_to_response(r) for r in step_rows]
    return _plan_row_to_response(plan_row, steps)


@router.post("", response_model=PlanResponse, status_code=201)
async def create_plan(plan: PlanCreate):
    """Create a new plan with steps."""
    # Validate steps list is non-empty
    if not plan.steps:
        raise HTTPException(status_code=422, detail="Plan must have at least one step")

    # Validate expires_hours
    if plan.expires_hours > 72:
        raise HTTPException(status_code=422, detail="expires_hours must be <= 72")

    # Validate failure_policy on each step
    for step in plan.steps:
        if step.failure_policy not in VALID_FAILURE_POLICIES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid failure_policy '{step.failure_policy}' on step '{step.name}'. "
                f"Must be one of: {', '.join(sorted(VALID_FAILURE_POLICIES))}",
            )

    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        plan_id = f"PLN-{uuid.uuid4().hex[:8].upper()}"

        # Generate step IDs and build name-to-id map for depends_on resolution
        step_ids: dict[str, str] = {}
        for step in plan.steps:
            step_id = f"PSTEP-{uuid.uuid4().hex[:8].upper()}"
            step_ids[step.name] = step_id

        # Auto-compute targets as union of all step targets
        all_targets: set[str] = set()
        for step in plan.steps:
            all_targets.update(step.targets)

        # Insert the plan
        await db.execute(
            """INSERT INTO ops_plans
               (id, created_at, created_by, title, description, status, targets, expires_hours)
               VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)""",
            (
                plan_id,
                now,
                plan.created_by,
                plan.title,
                plan.description,
                json.dumps(sorted(all_targets)),
                plan.expires_hours,
            ),
        )

        # Insert steps with resolved depends_on
        for step in plan.steps:
            step_id = step_ids[step.name]

            # Resolve depends_on names to IDs
            resolved_deps = []
            for dep_name in step.depends_on:
                if dep_name not in step_ids:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Step '{step.name}' depends on unknown step '{dep_name}'",
                    )
                resolved_deps.append(step_ids[dep_name])

            await db.execute(
                """INSERT INTO ops_plan_steps
                   (id, plan_id, name, description, sequence, depends_on, action_type,
                    targets, params, failure_policy, max_retries, rollback, timeout)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    step_id,
                    plan_id,
                    step.name,
                    step.description,
                    step.sequence,
                    json.dumps(resolved_deps),
                    step.action_type,
                    json.dumps(step.targets),
                    json.dumps(step.params),
                    step.failure_policy,
                    step.max_retries,
                    json.dumps(step.rollback) if step.rollback else None,
                    step.timeout,
                ),
            )

        await db.commit()
        return await _fetch_plan_with_steps(db, plan_id)
    finally:
        await db.close()


@router.get("", response_model=list[PlanResponse])
async def list_plans(
    status: str | None = Query(None),
    created_by: str | None = Query(None),
):
    """List plans with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_plans WHERE 1=1"
        params: list = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if created_by:
            query += " AND created_by = ?"
            params.append(created_by)

        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query, params)
        plan_rows = await cursor.fetchall()

        results = []
        for plan_row in plan_rows:
            cursor = await db.execute(
                "SELECT * FROM ops_plan_steps WHERE plan_id = ? ORDER BY sequence ASC",
                (plan_row["id"],),
            )
            step_rows = await cursor.fetchall()
            steps = [_step_row_to_response(r) for r in step_rows]
            results.append(_plan_row_to_response(plan_row, steps))

        return results
    finally:
        await db.close()


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: str):
    """Get a single plan with all steps included."""
    db = await get_db()
    try:
        return await _fetch_plan_with_steps(db, plan_id)
    finally:
        await db.close()


@router.post("/{plan_id}/cancel", response_model=PlanResponse)
async def cancel_plan(plan_id: str):
    """Cancel a plan. Only draft, approved, or blocked plans can be cancelled."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_plans WHERE id = ?", (plan_id,))
        plan_row = await cursor.fetchone()
        if not plan_row:
            raise HTTPException(status_code=404, detail="Plan not found")

        if plan_row["status"] not in CANCELLABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel plan with status '{plan_row['status']}'. "
                f"Only {', '.join(sorted(CANCELLABLE_STATUSES))} plans can be cancelled.",
            )

        now = datetime.now(UTC).isoformat()
        await db.execute(
            "UPDATE ops_plans SET status = 'cancelled', completed_at = ? WHERE id = ?",
            (now, plan_id),
        )
        await db.commit()

        return await _fetch_plan_with_steps(db, plan_id)
    finally:
        await db.close()
