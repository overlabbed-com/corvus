"""CMDB (service registry) API endpoints."""

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request

from src.database import get_db
from src.models.cmdb import (
    BaselineBehavior,
    BulkClassifyItem,
    BulkSyncItem,
    ServiceRegister,
    ServiceResponse,
    ServiceUpdate,
)

logger = logging.getLogger(__name__)

# Valid alert_policy values — prevents silent suppression via arbitrary strings (E1.4)
VALID_ALERT_POLICIES = frozenset({"default", "silent", "critical-only", "all"})

# Story 1.4: Valid field names for UPDATE operations — prevents SQL injection via dynamic column names
VALID_UPDATE_FIELDS = frozenset({
    "host",
    "service_type",
    "critical",
    "dependencies",
    "baseline_behavior",
    "alert_policy",
    "last_seen",
    "registered_by",
    "declared_image",
    "declared_healthcheck",
    "declared_env_hash",
    "declared_networks",
    "last_declared_at",
})



def _validate_update_fields(fields: list[str]) -> list[str]:
    """Validate field names against allowlist.


    Story 1.4: Prevents SQL injection via dynamic column names in UPDATE operations.
    All field names must be in VALID_UPDATE_FIELDS.


    Raises HTTPException if any field is invalid.
    """
    invalid = [f for f in fields if f not in VALID_UPDATE_FIELDS]
    if invalid:
        # Log as potential SQL injection attempt
        logger.warning(
            "Attempted SQL injection via invalid field names: %s",
            invalid,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Invalid field: {invalid[0]!r}. Valid fields: {', '.join(sorted(VALID_UPDATE_FIELDS))}",
        )
    return fields


def _build_update_sets(update: ServiceUpdate) -> tuple[list[str], list]:
    """Build SET clause from ServiceUpdate, validating field names.

    Story 1.4: Ensures only allowlisted fields can be updated.
    Returns (sets, params) for SQL UPDATE statement.
    """
    sets = []
    params = []
    # Track which fields are being updated for validation
    updated_fields: list[str] = []

    if update.host is not None:
        sets.append("host = ?")
        params.append(update.host)
        updated_fields.append("host")
    if update.service_type is not None:
        sets.append("service_type = ?")
        params.append(update.service_type)
        updated_fields.append("service_type")
    if update.critical is not None:
        sets.append("critical = ?")
        params.append(1 if update.critical else 0)
        updated_fields.append("critical")
    if update.dependencies is not None:
        sets.append("dependencies = ?")
        params.append(json.dumps(update.dependencies))
        updated_fields.append("dependencies")
    if update.baseline_behavior is not None:
        sets.append("baseline_behavior = ?")
        params.append(json.dumps(update.baseline_behavior))
        updated_fields.append("baseline_behavior")
    if update.alert_policy is not None:
        # E1.4: Validate alert_policy against allowlist
        if update.alert_policy not in VALID_ALERT_POLICIES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid alert_policy '{update.alert_policy}'. "
                f"Valid values: {', '.join(sorted(VALID_ALERT_POLICIES))}",
            )
        sets.append("alert_policy = ?")
        params.append(update.alert_policy)
        updated_fields.append("alert_policy")

    # Story 1.4: Validate all updated field names against allowlist
    _validate_update_fields(updated_fields)

    return sets, params


router = APIRouter(prefix="/ops/cmdb", tags=["cmdb"])


def _row_to_response(row) -> ServiceResponse:
    return ServiceResponse(
        id=row["id"],
        name=row["name"],
        host=row["host"],
        service_type=row["service_type"],
        critical=bool(row["critical"]),
        dependencies=json.loads(row["dependencies"]),
        last_seen=row["last_seen"],
        baseline_behavior=json.loads(row["baseline_behavior"]),
        alert_policy=row["alert_policy"],
        created_at=row["created_at"],
        registered_by=row["registered_by"],
    )


@router.post("/register", response_model=ServiceResponse, status_code=201)
async def register_service(service: ServiceRegister):
    """Register a new service in the CMDB."""
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()

        # Upsert — update last_seen if already exists
        cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (service.name,))
        existing = await cursor.fetchone()

        if existing:
            await db.execute(
                """UPDATE ops_cmdb SET host = COALESCE(?, host),
                   service_type = COALESCE(?, service_type),
                   critical = ?, dependencies = ?, last_seen = ?,
                   registered_by = COALESCE(?, registered_by)
                   WHERE name = ?""",
                (
                    service.host,
                    service.service_type,
                    1 if service.critical else 0,
                    json.dumps(service.dependencies),
                    now,
                    service.registered_by,
                    service.name,
                ),
            )
        else:
            await db.execute(
                """INSERT INTO ops_cmdb
                   (id, name, host, service_type, critical, dependencies,
                    last_seen, created_at, registered_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    service.name,
                    service.name,
                    service.host,
                    service.service_type,
                    1 if service.critical else 0,
                    json.dumps(service.dependencies),
                    now,
                    now,
                    service.registered_by,
                ),
            )

        await db.commit()

        cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (service.name,))
        row = await cursor.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()


@router.get("", response_model=list[ServiceResponse])
async def list_services(
    service_type: str | None = Query(None),
    critical: bool | None = Query(None),
    host: str | None = Query(None),
):
    """List CMDB services with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_cmdb WHERE 1=1"
        params: list = []

        if service_type:
            query += " AND service_type = ?"
            params.append(service_type)
        if critical is not None:
            query += " AND critical = ?"
            params.append(1 if critical else 0)
        if host:
            query += " AND host = ?"
            params.append(host)

        query += " ORDER BY name"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        await db.close()


@router.get("/{name}", response_model=ServiceResponse)
async def get_service(name: str):
    """Get service details by name."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (name,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Service not found")
        return _row_to_response(row)
    finally:
        await db.close()


@router.post("/{name}/baseline", response_model=ServiceResponse)
async def set_baseline(name: str, baseline: BaselineBehavior):
    """Set baseline behavior for a service."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (name,))
        existing = await cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Service not found")

        await db.execute(
            "UPDATE ops_cmdb SET baseline_behavior = ? WHERE name = ?",
            (json.dumps(baseline.model_dump()), name),
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (name,))
        row = await cursor.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()


@router.patch("/{name}", response_model=ServiceResponse)
async def update_service(name: str, update: ServiceUpdate, request: Request):
    """Update service metadata."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (name,))
        existing = await cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Service not found")

        # Story 1.4: Build SET clause with field validation
        sets, params = _build_update_sets(update)


        if not sets:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(name)
        await db.execute(
            f"UPDATE ops_cmdb SET {', '.join(sets)} WHERE name = ?",  # nosec B608 - Field names validated by _build_update_sets
            params,
        )
        await db.commit()

        # E1.4: Audit alert_policy changes — these suppress monitoring
        if update.alert_policy is not None and update.alert_policy != existing["alert_policy"]:
            actor = "anonymous"
            if hasattr(request.state, "auth"):
                actor = request.state.auth.identity
            logger.warning(
                "alert_policy changed on %s: %s -> %s by %s",
                name,
                existing["alert_policy"],
                update.alert_policy,
                actor,
            )
            # Emit audit event so the change is visible in the event stream
            try:
                import uuid

                event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
                now = datetime.now(UTC).isoformat()
                await db.execute(
                    """INSERT INTO ops_events
                       (id, timestamp, source, type, target, severity, data, authenticated_as)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id,
                        now,
                        "corvus",
                        "cmdb.alert_policy_changed",
                        name,
                        "warning",
                        json.dumps(
                            {
                                "old_policy": existing["alert_policy"],
                                "new_policy": update.alert_policy,
                                "changed_by": actor,
                            }
                        ),
                        actor,
                    ),
                )
                await db.commit()
            except Exception:
                logger.exception("Failed to emit alert_policy change event for %s", name)

        cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (name,))
        row = await cursor.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()


@router.post("/bulk-sync")
async def bulk_sync(services: list[BulkSyncItem]):
    """Bulk import/update services from discovery."""
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        created = 0
        updated = 0

        for svc in services:
            cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (svc.name,))
            existing = await cursor.fetchone()

            if existing:
                await db.execute(
                    """UPDATE ops_cmdb SET host = COALESCE(?, host),
                       service_type = COALESCE(?, service_type),
                       critical = ?, dependencies = ?, last_seen = ?
                       WHERE name = ?""",
                    (
                        svc.host,
                        svc.service_type,
                        1 if svc.critical else 0,
                        json.dumps(svc.dependencies),
                        now,
                        svc.name,
                    ),
                )
                updated += 1
            else:
                await db.execute(
                    """INSERT INTO ops_cmdb
                       (id, name, host, service_type, critical, dependencies,
                        last_seen, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        svc.name,
                        svc.name,
                        svc.host,
                        svc.service_type,
                        1 if svc.critical else 0,
                        json.dumps(svc.dependencies),
                        now,
                        now,
                    ),
                )
                created += 1

        await db.commit()
        return {"status": "synced", "created": created, "updated": updated}
    finally:
        await db.close()


@router.post("/bulk-classify")
async def bulk_classify(items: list[BulkClassifyItem]):
    """Bulk assign service_type to services."""
    db = await get_db()
    try:
        classified = 0
        not_found = 0

        for item in items:
            cursor = await db.execute("SELECT * FROM ops_cmdb WHERE name = ?", (item.name,))
            existing = await cursor.fetchone()
            if existing:
                await db.execute(
                    "UPDATE ops_cmdb SET service_type = ? WHERE name = ?",
                    (item.service_type, item.name),
                )
                classified += 1
            else:
                not_found += 1

        await db.commit()
        return {"status": "classified", "classified": classified, "not_found": not_found}
    finally:
        await db.close()
