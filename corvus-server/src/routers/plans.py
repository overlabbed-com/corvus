"""Plan execution API endpoints — CRUD for multi-step operational plans."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from src.config import CHANGE_EXPIRY_HOURS
from src.database import get_db
from src.models.plans import (
    PlanApproveRequest,
    PlanCreate,
    PlanResponse,
    PlanStatusResponse,
    PlanStepResponse,
    StepResultRequest,
)
from src.tasks.trust_ledger import get_trust_tier

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


@router.post("/{plan_id}/approve")
async def approve_plan(plan_id: str, request: PlanApproveRequest):
    """Approve a plan using trust ledger gating.

    Checks each step's action_type (plus plan.execute) against the trust ledger.
    If all are AUTO or SUPERVISED, auto-approves. If any are ESCALATE, requires
    force=True for human override.
    """
    db = await get_db()
    try:
        # 1. Verify plan exists and is in draft status
        cursor = await db.execute("SELECT * FROM ops_plans WHERE id = ?", (plan_id,))
        plan_row = await cursor.fetchone()
        if not plan_row:
            raise HTTPException(status_code=404, detail="Plan not found")

        if plan_row["status"] != "draft":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot approve plan with status '{plan_row['status']}'. "
                "Only draft plans can be approved.",
            )

        # 2. Collect unique action_types from all steps
        cursor = await db.execute(
            "SELECT * FROM ops_plan_steps WHERE plan_id = ? ORDER BY sequence ASC",
            (plan_id,),
        )
        step_rows = await cursor.fetchall()
        steps = [_step_row_to_response(r) for r in step_rows]

        action_types: set[str] = set()
        for step in steps:
            action_types.add(step.action_type)
        # Include plan.execute (Advocate finding #6) — gates right to start execution
        action_types.add("plan.execute")

        # 3. Query trust ledger for each action_type
        tier_map: dict[str, str] = {}
        for action_type in action_types:
            tier_info = await get_trust_tier(action_type)
            tier_map[action_type] = tier_info["trust_tier"]

        # 4. Decision logic
        escalated_action_types = {
            at for at, tier in tier_map.items() if tier == "ESCALATE"
        }

        if escalated_action_types:
            if request.force:
                # Human override — approve with method "human"
                approval_method = "human"
            else:
                # Return needs_approval response with escalated steps
                escalated_steps = [
                    {
                        "step_id": s.id,
                        "step_name": s.name,
                        "action_type": s.action_type,
                        "trust_tier": tier_map[s.action_type],
                    }
                    for s in steps
                    if s.action_type in escalated_action_types
                ]
                # Also include plan.execute if it's escalated
                if "plan.execute" in escalated_action_types:
                    escalated_steps.append(
                        {
                            "step_id": None,
                            "step_name": "plan.execute",
                            "action_type": "plan.execute",
                            "trust_tier": "ESCALATE",
                        }
                    )
                return {
                    "needs_approval": True,
                    "plan_id": plan_id,
                    "escalated_steps": escalated_steps,
                }
        else:
            # All AUTO or SUPERVISED — auto-approve
            approval_method = "trust_ledger"

        # Approve the plan
        now = datetime.now(UTC)
        approved_at = now.isoformat()
        expires_at = (now + timedelta(hours=plan_row["expires_hours"])).isoformat()

        await db.execute(
            """UPDATE ops_plans
               SET status = 'approved',
                   approval_method = ?,
                   approved_at = ?,
                   approved_by = ?,
                   expires_at = ?
               WHERE id = ?""",
            (approval_method, approved_at, request.approved_by, expires_at, plan_id),
        )
        await db.commit()

        return await _fetch_plan_with_steps(db, plan_id)
    finally:
        await db.close()


# ---- DAG helper ----


async def _evaluate_dag(db, plan_id: str) -> list[dict]:
    """Find pending steps whose dependencies are all completed/skipped.

    Mark them as ready. Return list of newly-ready step dicts.
    """
    cursor = await db.execute(
        "SELECT * FROM ops_plan_steps WHERE plan_id = ? ORDER BY sequence ASC",
        (plan_id,),
    )
    all_steps = await cursor.fetchall()

    # Build set of completed/skipped step IDs
    done_ids: set[str] = set()
    for s in all_steps:
        if s["status"] in ("completed", "skipped"):
            done_ids.add(s["id"])

    newly_ready: list[dict] = []
    for s in all_steps:
        if s["status"] != "pending":
            continue
        deps = json.loads(s["depends_on"])
        if all(dep_id in done_ids for dep_id in deps):
            await db.execute(
                "UPDATE ops_plan_steps SET status = 'ready' WHERE id = ?",
                (s["id"],),
            )
            newly_ready.append(dict(s))

    return newly_ready


async def _check_plan_completion(db, plan_id: str) -> bool:
    """Check if all steps are terminal (completed/skipped/failed).

    If so, mark plan completed and close the change window. Returns True if plan completed.
    When plan is rolling_back and all rollback steps complete, outcome is rolled_back.
    """
    cursor = await db.execute(
        "SELECT status FROM ops_plan_steps WHERE plan_id = ?",
        (plan_id,),
    )
    step_rows = await cursor.fetchall()
    statuses = [r["status"] for r in step_rows]

    terminal = {"completed", "skipped", "failed"}
    if not all(s in terminal for s in statuses):
        return False

    now = datetime.now(UTC).isoformat()

    # Check current plan status to determine outcome
    cursor = await db.execute("SELECT status, change_id FROM ops_plans WHERE id = ?", (plan_id,))
    plan_row = await cursor.fetchone()

    if plan_row["status"] == "rolling_back":
        # All rollback steps finished -> plan failed with rolled_back outcome
        final_status = "failed"
        outcome = "rolled_back"
    else:
        has_failures = "failed" in statuses
        final_status = "completed"
        outcome = "partial" if has_failures else "success"

    await db.execute(
        "UPDATE ops_plans SET status = ?, completed_at = ?, outcome = ? WHERE id = ?",
        (final_status, now, outcome, plan_id),
    )

    # Close the change window
    if plan_row["change_id"]:
        await db.execute(
            "UPDATE ops_changes SET status = 'completed', completed_at = ?, outcome = ? WHERE id = ?",
            (now, outcome, plan_row["change_id"]),
        )

    return True


# ---- Execution endpoints ----


@router.post("/{plan_id}/execute", response_model=PlanResponse)
async def execute_plan(plan_id: str):
    """Execute an approved plan: create change window, mark root steps ready."""
    db = await get_db()
    try:
        # Verify plan exists and is approved
        cursor = await db.execute("SELECT * FROM ops_plans WHERE id = ?", (plan_id,))
        plan_row = await cursor.fetchone()
        if not plan_row:
            raise HTTPException(status_code=404, detail="Plan not found")

        if plan_row["status"] != "approved":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot execute plan with status '{plan_row['status']}'. "
                "Only approved plans can be executed.",
            )

        now = datetime.now(UTC)
        now_iso = now.isoformat()
        targets = json.loads(plan_row["targets"])

        # Create change window (same pattern as changes.py create_change)
        change_id = f"CHG-{uuid.uuid4().hex[:8].upper()}"
        expires_at = (now + timedelta(hours=plan_row["expires_hours"])).isoformat()

        await db.execute(
            """INSERT INTO ops_changes
               (id, created_at, created_by, status, targets, description,
                auto_expire, expires_at)
               VALUES (?, ?, ?, 'active', ?, ?, 1, ?)""",
            (
                change_id,
                now_iso,
                plan_row["created_by"],
                json.dumps(targets),
                f"Plan execution: {plan_row['title']}",
                expires_at,
            ),
        )

        # Update plan: set change_id, status = executing
        await db.execute(
            "UPDATE ops_plans SET status = 'executing', change_id = ? WHERE id = ?",
            (change_id, plan_id),
        )

        # Mark root steps (empty depends_on) as ready
        cursor = await db.execute(
            "SELECT * FROM ops_plan_steps WHERE plan_id = ?",
            (plan_id,),
        )
        step_rows = await cursor.fetchall()
        for s in step_rows:
            deps = json.loads(s["depends_on"])
            if not deps:
                await db.execute(
                    "UPDATE ops_plan_steps SET status = 'ready' WHERE id = ?",
                    (s["id"],),
                )

        # Emit plan.started event (same pattern as events.py)
        event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_events
               (id, timestamp, source, type, target, severity, data, related_change_id)
               VALUES (?, ?, 'corvus', 'plan.started', ?, 'info', ?, ?)""",
            (
                event_id,
                now_iso,
                plan_row["title"],
                json.dumps({"summary": f"Plan '{plan_row['title']}' execution started", "plan_id": plan_id}),
                change_id,
            ),
        )

        await db.commit()
        return await _fetch_plan_with_steps(db, plan_id)
    finally:
        await db.close()


@router.get("/{plan_id}/steps/ready", response_model=list[PlanStepResponse])
async def get_ready_steps(plan_id: str):
    """Return steps that are ready and claim them by marking as executing."""
    db = await get_db()
    try:
        # Verify plan exists
        cursor = await db.execute("SELECT id FROM ops_plans WHERE id = ?", (plan_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Plan not found")

        now_iso = datetime.now(UTC).isoformat()

        cursor = await db.execute(
            "SELECT * FROM ops_plan_steps WHERE plan_id = ? AND status = 'ready' ORDER BY sequence ASC",
            (plan_id,),
        )
        ready_rows = await cursor.fetchall()

        # Claim: mark each as executing with started_at
        for r in ready_rows:
            await db.execute(
                "UPDATE ops_plan_steps SET status = 'executing', started_at = ? WHERE id = ?",
                (now_iso, r["id"]),
            )
        await db.commit()

        # Re-fetch to get updated status
        step_ids = [r["id"] for r in ready_rows]
        results = []
        for sid in step_ids:
            cursor = await db.execute("SELECT * FROM ops_plan_steps WHERE id = ?", (sid,))
            row = await cursor.fetchone()
            results.append(_step_row_to_response(row))

        return results
    finally:
        await db.close()


@router.post("/{plan_id}/steps/{step_id}/result")
async def report_step_result(plan_id: str, step_id: str, req: StepResultRequest):
    """Report step completion/failure and advance the DAG.

    On success: mark completed, evaluate DAG for next steps.
    On failure: apply failure_policy (halt/skip/retry).
    """
    db = await get_db()
    try:
        # Verify plan and step exist
        cursor = await db.execute("SELECT id, status FROM ops_plans WHERE id = ?", (plan_id,))
        plan_row = await cursor.fetchone()
        if not plan_row:
            raise HTTPException(status_code=404, detail="Plan not found")

        cursor = await db.execute(
            "SELECT * FROM ops_plan_steps WHERE id = ? AND plan_id = ?",
            (step_id, plan_id),
        )
        step_row = await cursor.fetchone()
        if not step_row:
            raise HTTPException(status_code=404, detail="Step not found")

        now_iso = datetime.now(UTC).isoformat()
        newly_ready: list[dict] = []
        retry_count = step_row["retry_count"]

        if req.success:
            # --- Success path ---
            new_status = "completed"
            await db.execute(
                "UPDATE ops_plan_steps SET status = ?, completed_at = ?, output = ?, error = ? WHERE id = ?",
                (
                    new_status,
                    now_iso,
                    json.dumps(req.output) if req.output else None,
                    req.error,
                    step_id,
                ),
            )
            newly_ready = await _evaluate_dag(db, plan_id)

        else:
            # --- Failure path: apply failure_policy ---
            policy = step_row["failure_policy"]
            retry_count += 1

            if policy == "retry" and retry_count <= step_row["max_retries"]:
                # Re-queue: reset to ready, clear started_at, bump retry_count
                new_status = "ready"
                await db.execute(
                    "UPDATE ops_plan_steps SET status = 'ready', started_at = NULL, "
                    "retry_count = ?, error = ? WHERE id = ?",
                    (retry_count, req.error, step_id),
                )

            elif policy == "skip":
                # Mark skipped (treated as done for dependency resolution)
                new_status = "skipped"
                await db.execute(
                    "UPDATE ops_plan_steps SET status = 'skipped', completed_at = ?, "
                    "output = ?, error = ?, retry_count = ? WHERE id = ?",
                    (
                        now_iso,
                        json.dumps(req.output) if req.output else None,
                        req.error,
                        retry_count,
                        step_id,
                    ),
                )
                newly_ready = await _evaluate_dag(db, plan_id)

            else:
                # halt (default), or retry exhausted
                new_status = "failed"
                await db.execute(
                    "UPDATE ops_plan_steps SET status = 'failed', completed_at = ?, "
                    "output = ?, error = ?, retry_count = ? WHERE id = ?",
                    (
                        now_iso,
                        json.dumps(req.output) if req.output else None,
                        req.error,
                        retry_count,
                        step_id,
                    ),
                )
                # Block the plan and emit event
                await db.execute(
                    "UPDATE ops_plans SET status = 'blocked' WHERE id = ?",
                    (plan_id,),
                )
                event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
                await db.execute(
                    """INSERT INTO ops_events
                       (id, timestamp, source, type, target, severity, data, related_change_id)
                       VALUES (?, ?, 'corvus', 'plan.blocked', ?, 'warning', ?, ?)""",
                    (
                        event_id,
                        now_iso,
                        step_row["name"],
                        json.dumps({
                            "summary": f"Plan blocked: step '{step_row['name']}' failed",
                            "plan_id": plan_id,
                            "step_id": step_id,
                            "error": req.error,
                        }),
                        plan_row["status"] if plan_row["status"] != "blocked" else None,
                    ),
                )

        # Check if plan is complete (handles both normal and rolling_back)
        await _check_plan_completion(db, plan_id)

        await db.commit()

        # Determine current plan status
        cursor = await db.execute("SELECT status FROM ops_plans WHERE id = ?", (plan_id,))
        updated_plan = await cursor.fetchone()

        response = {
            "step_id": step_id,
            "step_status": new_status,
            "plan_status": updated_plan["status"],
            "retry_count": retry_count,
            "next_ready_steps": [
                {"id": s["id"], "name": s["name"], "action_type": s["action_type"]}
                for s in newly_ready
            ],
        }
        return response
    finally:
        await db.close()


@router.post("/{plan_id}/rollback")
async def rollback_plan(plan_id: str):
    """Trigger rollback: create reverse-order rollback steps for completed steps."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_plans WHERE id = ?", (plan_id,))
        plan_row = await cursor.fetchone()
        if not plan_row:
            raise HTTPException(status_code=404, detail="Plan not found")

        if plan_row["status"] not in ("completed", "blocked"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot rollback plan with status '{plan_row['status']}'. "
                "Only completed or blocked plans can be rolled back.",
            )

        now_iso = datetime.now(UTC).isoformat()

        # Set plan status to rolling_back
        await db.execute(
            "UPDATE ops_plans SET status = 'rolling_back' WHERE id = ?",
            (plan_id,),
        )

        # Find completed steps with rollback definitions, ordered by sequence DESC
        cursor = await db.execute(
            "SELECT * FROM ops_plan_steps WHERE plan_id = ? AND status = 'completed' "
            "ORDER BY sequence DESC",
            (plan_id,),
        )
        completed_steps = await cursor.fetchall()

        # Filter to steps that have a rollback definition
        rollback_candidates = [
            s for s in completed_steps
            if s["rollback"] and json.loads(s["rollback"])
        ]

        # Create rollback steps chained in reverse order
        prev_rb_id: str | None = None
        for step in rollback_candidates:
            rb_def = json.loads(step["rollback"])
            rb_id = f"PSTEP-{uuid.uuid4().hex[:8].upper()}"

            depends_on = [prev_rb_id] if prev_rb_id else []
            status = "ready" if not prev_rb_id else "pending"

            await db.execute(
                """INSERT INTO ops_plan_steps
                   (id, plan_id, name, description, sequence, depends_on, action_type,
                    targets, params, failure_policy, max_retries, rollback, timeout, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'halt', 0, NULL, 300, ?)""",
                (
                    rb_id,
                    plan_id,
                    f"rollback:{step['name']}",
                    f"Rollback for step '{step['name']}'",
                    -step["sequence"],  # negative of original sequence
                    json.dumps(depends_on),
                    rb_def.get("action_type", step["action_type"]),
                    step["targets"],  # same targets as original
                    json.dumps(rb_def.get("params", {})),
                    status,
                ),
            )
            prev_rb_id = rb_id

        # Emit plan.rolling_back event
        event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
        await db.execute(
            """INSERT INTO ops_events
               (id, timestamp, source, type, target, severity, data, related_change_id)
               VALUES (?, ?, 'corvus', 'plan.rolling_back', ?, 'warning', ?, ?)""",
            (
                event_id,
                now_iso,
                plan_row["title"],
                json.dumps({
                    "summary": f"Plan '{plan_row['title']}' rolling back",
                    "plan_id": plan_id,
                    "rollback_steps": len(rollback_candidates),
                }),
                plan_row["change_id"],
            ),
        )

        await db.commit()
        return await _fetch_plan_with_steps(db, plan_id)
    finally:
        await db.close()


@router.get("/{plan_id}/status", response_model=PlanStatusResponse)
async def get_plan_status(plan_id: str):
    """Get plan execution status with step counts and progress."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_plans WHERE id = ?", (plan_id,))
        plan_row = await cursor.fetchone()
        if not plan_row:
            raise HTTPException(status_code=404, detail="Plan not found")

        cursor = await db.execute(
            "SELECT status FROM ops_plan_steps WHERE plan_id = ?",
            (plan_id,),
        )
        step_rows = await cursor.fetchall()
        statuses = [r["status"] for r in step_rows]

        total = len(statuses)
        counts = {
            "pending": statuses.count("pending"),
            "ready": statuses.count("ready"),
            "executing": statuses.count("executing"),
            "completed": statuses.count("completed"),
            "failed": statuses.count("failed"),
            "skipped": statuses.count("skipped"),
            "rolled_back": statuses.count("rolled_back"),
        }
        done = counts["completed"] + counts["skipped"]
        progress_pct = (done / total * 100) if total > 0 else 0.0

        return PlanStatusResponse(
            id=plan_id,
            status=plan_row["status"],
            title=plan_row["title"],
            change_id=plan_row["change_id"],
            total_steps=total,
            progress_pct=round(progress_pct, 1),
            **counts,
        )
    finally:
        await db.close()
