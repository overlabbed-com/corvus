"""Event API endpoints."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import EventSourceResponse

from src.database import get_db
from src.event_bus import publish, record_event, record_incident_state, subscribe
from src.models.events import EventCreate, EventResponse, TargetStatus
from src.ocsf import transform_to_ocsf
from src.sanitizer import sanitize
from src.siem.forwarder import get_dead_letters, get_forwarding_stats, resolve_dead_letter
from src.tasks.trust_ledger import get_trust_tier as _get_trust

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/events", tags=["events"])


def _row_to_response(row) -> EventResponse:
    return EventResponse(
        id=row["id"],
        timestamp=row["timestamp"],
        source=row["source"],
        type=row["type"],
        target=row["target"],
        severity=row["severity"],
        data=json.loads(row["data"]),
        related_incident_id=row["related_incident_id"],
        related_change_id=row["related_change_id"],
        related_problem_id=row["related_problem_id"],
        parent_event_id=row["parent_event_id"],
        authenticated_as=row["authenticated_as"],
        signature=row["signature"] if "signature" in row else None,  # noqa: SIM401
    )


@router.post("", response_model=EventResponse, status_code=201)
async def emit_event(event: EventCreate, request: Request):
    """Emit a new operational event."""
    # GAP-1/3: Validate event type before model validation
    from src.models.events import EVENT_TYPE_ALLOWLIST, VALID_SEVERITIES

    if event.type not in EVENT_TYPE_ALLOWLIST:
        valid = sorted(EVENT_TYPE_ALLOWLIST)
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event type: {event.type!r}; valid_types={valid}",
        )

    if event.severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity: {event.severity!r}. Must be one of: {sorted(VALID_SEVERITIES)}",
        )

    # Record authenticated identity (S1.2 — prevents agent impersonation)
    authenticated_as = "anonymous"
    if hasattr(request.state, "auth"):
        authenticated_as = request.state.auth.identity

    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"

        # Sanitize event data before storage — secrets in log excerpts
        sanitized_data = sanitize(json.dumps(event.data))

        # GAP-8: Sign event before storage
        from src.event_signing import sign_event

        event_row = {
            "id": event_id,
            "timestamp": now,
            "source": event.source,
            "type": event.type,
            "target": event.target,
            "severity": event.severity,
            "data": event.data,
        }
        signature = sign_event(event_row)

        await db.execute(
            """INSERT INTO ops_events
               (id, timestamp, source, type, target, severity, data,
                related_incident_id, related_change_id, related_problem_id,
                parent_event_id, authenticated_as, signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                now,
                event.source,
                event.type,
                event.target,
                event.severity,
                sanitized_data,
                event.related_incident_id,
                event.related_change_id,
                event.related_problem_id,
                event.parent_event_id,
                authenticated_as,
                signature,
            ),
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM ops_events WHERE id = ?", (event_id,))
        row = await cursor.fetchone()
        response = _row_to_response(row)

        # Transform to OCSF and forward to SIEM
        ocsf_input = dict(row)
        ocsf_input["data"] = json.loads(ocsf_input.get("data", "{}"))
        ocsf_event = transform_to_ocsf(ocsf_input)

        # Fire-and-forget SIEM forwarding
        import asyncio

        from src.siem.forwarder import forward_to_siem

        asyncio.create_task(forward_to_siem(ocsf_event))

        # Publish to SSE subscribers (GAP-4)
        event_dict = response.model_dump()
        asyncio.create_task(publish(event_dict))

        # Record for anomaly detection (GAP-5)
        record_event(event.type)

        # Contradiction detection for incident state changes (GAP-6)
        if event.type in ("incident.opened", "incident.resolved"):
            incident_id = event.related_incident_id or event.target
            if incident_id:
                contradictions = record_incident_state(incident_id, event.type)
                for gap in contradictions:
                    logger.warning(
                        f"Contradiction detected: incident {gap['incident_id']} "
                        f"resolved {gap['gap_minutes']}min before reopening"
                    )

        return response
    finally:
        await db.close()


@router.get("", response_model=list[EventResponse])
async def list_events(
    since: str | None = Query(None),
    severity: str | None = Query(None),
    target: str | None = Query(None),
    source: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(100, le=1000),
):
    """List events with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_events WHERE 1=1"
        params: list = []

        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if target:
            query += " AND target = ?"
            params.append(target)
        if source:
            query += " AND source = ?"
            params.append(source)
        if event_type:
            query += " AND type = ?"
            params.append(event_type)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        await db.close()


@router.get("/stream")
async def event_stream(request: Request):
    """Real-time event stream via SSE (GAP-4).

    Optional filters: severity, target, source, event_type.
    """
    filters = {}
    if request.query_params:
        for param in ("severity", "target", "source", "event_type"):
            if request.query_params.get(param):
                filters[param] = request.query_params.get(param)

    q, cancel_task = await subscribe(filters=filters or None)

    async def event_generator():
        try:
            while True:
                event = await q.get()
                yield {"event": event}
        except asyncio.CancelledError:
            cancel_task.cancel()
            return

    return EventSourceResponse(event_generator())


@router.get("/context")
async def get_context():
    """Session start briefing — last 24h events, active issues, gap summary."""
    from src.tasks.gap_detection import get_gap_summary

    db = await get_db()
    try:
        since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        severity_order = (
            "CASE severity"
            " WHEN 'critical' THEN 0"
            " WHEN 'high' THEN 1"
            " WHEN 'warning' THEN 2"
            " WHEN 'medium' THEN 3"
            " WHEN 'low' THEN 4"
            " ELSE 5 END"
        )
        cursor = await db.execute(
            f"SELECT * FROM ops_events WHERE timestamp >= ?"  # nosec B608
            f" ORDER BY {severity_order}, timestamp DESC LIMIT 100",
            (since,),
        )
        rows = await cursor.fetchall()
        events = [_row_to_response(r) for r in rows]

        # Active incidents
        cursor = await db.execute(
            "SELECT id, target, severity, title, status FROM ops_incidents WHERE status IN ('open', 'investigating')"
        )
        active_incidents = [dict(r) for r in await cursor.fetchall()]

        # Active changes
        cursor = await db.execute(
            "SELECT id, created_by, targets, description FROM ops_changes WHERE status = 'active'"
        )
        active_changes = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    # Gap summary (uses its own db connection)
    gaps = await get_gap_summary()

    return {
        "events_24h": events,
        "active_incidents": active_incidents,
        "active_changes": active_changes,
        "gaps": gaps,
        "gap_summary": gaps,
    }


@router.get("/targets/{target}/status", response_model=TargetStatus)
async def get_target_status(
    target: str,
    action_type: str | None = Query(None, description="Type of action being planned (e.g., restart, deploy, stop)"),
    agent_name: str | None = Query(None, description="Name of the agent planning the action"),
):
    """Get consolidated target status with GO/CAUTION/STOP recommendation.

    Phase 2 Enhancement (Corvus-CAIPE Integration):
    - action_type: Used for more precise conflict detection
    - agent_name: Used for logging and tracking which agent is checking
    """
    db = await get_db()
    try:
        # Active changes on this target
        cursor = await db.execute(
            "SELECT * FROM ops_changes WHERE status = 'active' AND targets LIKE ?",
            (f"%{target}%",),
        )
        changes = await cursor.fetchall()
        active_changes: list[dict[str, Any]] = [
            {"id": c["id"], "created_by": c["created_by"], "description": c["description"]} for c in changes
        ]

        # Active incidents on this target
        cursor = await db.execute(
            "SELECT * FROM ops_incidents WHERE target = ? AND status IN ('open', 'investigating')",
            (target,),
        )
        incidents = await cursor.fetchall()
        active_incidents: list[dict[str, Any]] = [
            {"id": i["id"], "severity": i["severity"], "title": i["title"], "status": i["status"]} for i in incidents
        ]

        # Recent events (last 1h)
        since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        cursor = await db.execute(
            "SELECT * FROM ops_events WHERE target = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT 10",
            (target, since),
        )
        events = await cursor.fetchall()
        recent_events: list[dict[str, Any]] = [
            {"id": e["id"], "type": e["type"], "severity": e["severity"]} for e in events
        ]

        # Look up trust tier for this target's common action types
        # Phase 2: Use action_type if provided for more precise trust lookup
        trust_tier = "ESCALATE"
        cursor = await db.execute("SELECT service_type FROM ops_cmdb WHERE name = ?", (target,))
        cmdb_row = await cursor.fetchone()
        if cmdb_row and cmdb_row["service_type"]:
            svc_type = cmdb_row["service_type"]
            # If action_type is provided, use it for more precise trust lookup
            if action_type:
                trust_info = await _get_trust(f"{action_type}:{svc_type}")
            else:
                # Default to restart for backward compatibility
                trust_info = await _get_trust(f"remediation.restart:{svc_type}")
            trust_tier = trust_info["trust_tier"]

        # Determine recommendation
        recommendation = "GO"
        reason = "No active changes or incidents"

        if active_incidents:
            critical = any(i["severity"] in ("critical", "high") for i in active_incidents)
            if critical:
                recommendation = "STOP"
                inc = active_incidents[0]
                reason = f"Active critical/high incident: {inc['id']} — {inc['title']}"
            else:
                recommendation = "CAUTION"
                reason = f"Active incident: {active_incidents[0]['id']} — {active_incidents[0]['title']}"

        if active_changes:
            if recommendation == "GO":
                recommendation = "CAUTION"
                chg = active_changes[0]
                reason = f"Active change window: {chg['id']} by {chg['created_by']}"
            elif recommendation == "CAUTION":
                recommendation = "STOP"
                reason = "Active change AND incident on target"

        # Phase 2: Add action_type-specific reasoning
        if action_type and recommendation == "GO":
            # For write actions, be more cautious
            write_actions = ["restart", "stop", "start", "deploy", "update", "delete", "modify", "exec"]
            if action_type.lower() in write_actions:
                # Check if any agent is currently working on this target
                cursor = await db.execute(
                    """SELECT source, type, timestamp FROM ops_events 
                       WHERE target = ? AND type LIKE 'change.%'
                       AND timestamp >= datetime('now', '-5 minutes')
                       ORDER BY timestamp DESC LIMIT 1""",
                    (target,),
                )
                recent_change = await cursor.fetchone()
                if recent_change:
                    # Another agent recently worked on this target
                    recommendation = "CAUTION"
                    reason = f"Recent change activity on target by {recent_change['source']}: {recent_change['type']}"

        # Phase 2: Add agent_name to response for tracking
        return TargetStatus(
            target=target,
            recommendation=recommendation,
            reason=reason,
            active_changes=active_changes,
            active_incidents=active_incidents,
            recent_events=recent_events,
            trust_tier=trust_tier,
            action_type=action_type,
            agent_name=agent_name,
        )
    finally:
        await db.close()


@router.get("/siem/dead-letter")
async def list_dead_letters(
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
):
    """ "List SIEM dead-letter queue entries.


    Story 1.2: Failed events that couldn't be forwarded to SIEM
    are stored here for later retry or investigation.
    """
    dead_letters = await get_dead_letters(limit=limit, offset=offset)
    stats = await get_forwarding_stats()

    return {
        "dead_letters": dead_letters,
        "count": len(dead_letters),
        "total_dead_letter_count": stats.get("dead_letter_count", 0),
    }


@router.delete("/siem/dead-letter/{dl_id}")
async def resolve_dead_letter_entry(dl_id: str, request: Request):
    """ "Mark a dead-letter entry as resolved.


    Story 1.2: Allows manual resolution of dead-letter entries
    after the underlying issue has been fixed.
    """
    actor = "anonymous"
    if hasattr(request.state, "auth"):
        actor = request.state.auth.identity

    success = await resolve_dead_letter(dl_id, resolved_by=actor)

    if not success:
        raise HTTPException(status_code=404, detail="Dead-letter entry not found")

    return {"status": "resolved", "dl_id": dl_id, "resolved_by": actor}


# ============================================================================
# CAIPE Integration Endpoints (Phase 2)
# ============================================================================


@router.get("/agent-context")
async def get_agent_context(
    agent_name: str = Query(..., description="Name of the agent requesting context"),
    target: str | None = Query(None, description="Target service/container being worked on"),
    request: Request | None = None,
):
    """Get operational briefing for an agent working on a specific target.

    Phase 2 (Corvus-CAIPE Integration): Provides context tailored for CAIPE agents.

    Returns:
        - active_changes: Changes currently affecting the target
        - recent_incidents: Incidents related to the target
        - related_services: Services that depend on or are depended by the target
        - recommendations: Actionable recommendations based on current state
        - blast_radius: Impact analysis if target fails
        - dependency_chain: Upstream dependencies of the target
    """
    db = await get_db()
    try:
        context: dict[str, Any] = {
            "agent_name": agent_name,
            "target": target,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Get active changes for this agent/target
        active_changes = []
        rows = await db.fetch_all(
            """SELECT id, targets, description, status, created_at, created_by
               FROM ops_changes
               WHERE status IN ('open', 'in_progress')
               AND (targets LIKE ? OR created_by = ?)
               ORDER BY created_at DESC
               LIMIT 10""",
            (f"%{target}%" if target else "%", agent_name),
        )
        for row in rows:
            active_changes.append({
                "id": row["id"],
                "targets": json.loads(row["targets"]),
                "description": row["description"],
                "status": row["status"],
                "created_at": row["created_at"],
                "created_by": row["created_by"],
            })
        context["active_changes"] = active_changes

        # Get recent incidents for this agent/target
        recent_incidents = []
        rows = await db.fetch_all(
            """SELECT id, target, title, severity, status, detected_at
               FROM ops_incidents
               WHERE (target LIKE ? OR detected_by = ?)
               AND detected_at >= datetime('now', '-24 hours')
               ORDER BY detected_at DESC
               LIMIT 10""",
            (f"%{target}%" if target else "%", agent_name),
        )
        for row in rows:
            recent_incidents.append({
                "id": row["id"],
                "target": row["target"],
                "title": row["title"],
                "severity": row["severity"],
                "status": row["status"],
                "detected_at": row["detected_at"],
            })
        context["recent_incidents"] = recent_incidents

        # Get related services from CMDB
        related_services = []
        if target:
            rows = await db.fetch_all(
                """SELECT name, service_type, host, stack, criticality
                   FROM ops_services
                   WHERE name != ?
                   AND (name LIKE ? OR host LIKE ? OR stack LIKE ?)
                   ORDER BY criticality DESC, name
                   LIMIT 20""",
                (target, f"%{target}%", f"%{target}%", f"%{target}%"),
            )
            for row in rows:
                related_services.append({
                    "name": row["name"],
                    "service_type": row["service_type"],
                    "host": row["host"],
                    "stack": row["stack"],
                    "criticality": row["criticality"],
                })
        context["related_services"] = related_services

        # Get recent events for this agent/target
        recent_events = []
        rows = await db.fetch_all(
            """SELECT id, timestamp, source, type, target, severity, data
               FROM ops_events
               WHERE (target LIKE ? OR source = ?)
               AND timestamp >= datetime('now', '-1 hour')
               ORDER BY timestamp DESC
               LIMIT 20""",
            (f"%{target}%" if target else "%", agent_name),
        )
        for row in rows:
            recent_events.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "source": row["source"],
                "type": row["type"],
                "target": row["target"],
                "severity": row["severity"],
                "data": json.loads(row["data"]) if row["data"] else {},
            })
        context["recent_events"] = recent_events

        # Generate recommendations
        recommendations = []
        
        # Recommendation: Check for active changes
        if active_changes:
            for change in active_changes:
                if target and target in json.loads(change["targets"]):
                    recommendations.append({
                        "type": "warning",
                        "message": f"Active change {change['id']} is in progress for this target",
                        "action": "Review change before proceeding",
                        "priority": "high",
                    })
        
        # Recommendation: Check for recent incidents
        if recent_incidents:
            critical_incidents = [i for i in recent_incidents if i["severity"] in ["critical", "high"]]
            if critical_incidents:
                recommendations.append({
                    "type": "warning",
                    "message": f"{len(critical_incidents)} critical/high severity incidents detected",
                    "action": "Investigate incidents before proceeding",
                    "priority": "high",
                })
        
        # Recommendation: Check target status
        if target:
            target_status = await _get_target_status(db, target)
            if target_status:
                context["target_status"] = target_status
                if target_status.get("recommendation") == "STOP":
                    recommendations.append({
                        "type": "error",
                        "message": f"Target {target} has STOP recommendation",
                        "action": "DO NOT PROCEED - another agent is working on this target",
                        "priority": "critical",
                    })
                elif target_status.get("recommendation") == "CAUTION":
                    recommendations.append({
                        "type": "warning",
                        "message": f"Target {target} has CAUTION recommendation",
                        "action": "Review carefully before proceeding",
                        "priority": "medium",
                    })
        
        # Recommendation: Check for related service issues
        if related_services:
            unhealthy_services = []
            # This would need to query health endpoints, but for now we'll skip
            # as it could be slow. In production, this would be implemented.
            pass
        
        if not recommendations:
            recommendations.append({
                "type": "info",
                "message": "No issues detected",
                "action": "Proceed with normal operations",
                "priority": "low",
            })
        
        context["recommendations"] = recommendations

        return context

    finally:
        await db.close()


async def _get_target_status(db, target: str) -> dict | None:
    """Get the current status for a target (used by agent-context endpoint)."""
    # Check for active changes
    rows = await db.fetch_all(
        """SELECT id, status, description, created_by
           FROM ops_changes
           WHERE targets LIKE ? AND status IN ('open', 'in_progress')
           ORDER BY created_at DESC
           LIMIT 1""",
        (f"%{target}%",),
    )
    
    if rows:
        change = rows[0]
        if change["status"] in ["open", "in_progress"]:
            return {
                "recommendation": "CAUTION",
                "reason": f"Change {change['id']} is in progress",
                "change_id": change["id"],
                "change_status": change["status"],
                "change_description": change["description"],
            }
    
    # Check for active incidents
    rows = await db.fetch_all(
        """SELECT id, severity, title, status
           FROM ops_incidents
           WHERE target LIKE ? AND status IN ('open', 'investigating')
           ORDER BY detected_at DESC
           LIMIT 1""",
        (f"%{target}%",),
    )
    
    if rows:
        incident = rows[0]
        if incident["severity"] in ["critical", "high"]:
            return {
                "recommendation": "STOP",
                "reason": f"Critical incident {incident['id']} is active",
                "incident_id": incident["id"],
                "incident_severity": incident["severity"],
                "incident_title": incident["title"],
            }
        else:
            return {
                "recommendation": "CAUTION",
                "reason": f"Incident {incident['id']} is active",
                "incident_id": incident["id"],
                "incident_severity": incident["severity"],
                "incident_title": incident["title"],
            }
    
    # No issues found
    return {
        "recommendation": "GO",
        "reason": "No active changes or incidents for target",
    }
