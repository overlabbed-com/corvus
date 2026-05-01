"""Story 5.6: Batch event ingestion endpoint.

Efficient bulk event submission to reduce database write amplification.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.database import get_db
from src.event_bus import publish
from src.event_signing import sign_event
from src.models.events import VALID_SEVERITIES
from src.ocsf import transform_to_ocsf
from src.siem.forwarder import forward_to_siem

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


class BatchEventCreate(BaseModel):
    """Batch event submission."""

    events: list[dict] = Field(..., min_length=1, max_length=100)


class BatchEventResponse(BaseModel):
    """Response for batch event submission."""

    total: int
    accepted: int
    rejected: int
    event_ids: list[str]
    errors: list[dict]


@router.post("/ops/events/batch", response_model=BatchEventResponse)
async def emit_events_batch(events: BatchEventCreate, request: Request):
    """Emit multiple events in a single batch.

    Story 5.6: Reduces database write amplification for bulk submissions.

    Args:
        events: List of event objects (max 100)

    Returns:
        BatchEventResponse with counts and IDs
    """
    from src.models.events import EVENT_TYPE_ALLOWLIST

    authenticated_as = "anonymous"
    if hasattr(request.state, "auth"):
        authenticated_as = request.state.auth.identity

    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        accepted = 0
        rejected = 0
        event_ids = []
        errors = []

        for idx, event_data in enumerate(events.events):
            try:
                # Validate event type
                event_type = event_data.get("type")
                if event_type not in EVENT_TYPE_ALLOWLIST:
                    errors.append({"index": idx, "error": f"Unknown event type: {event_type}"})
                    rejected += 1
                    continue

                # Validate severity
                severity = event_data.get("severity", "info")
                if severity not in VALID_SEVERITIES:
                    errors.append({"index": idx, "error": f"Invalid severity: {severity}"})
                    rejected += 1
                    continue

                # Create event
                event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
                sanitized_data = json.dumps(event_data.get("data", {}))

                # Sign event
                event_row = {
                    "id": event_id,
                    "timestamp": now,
                    "source": event_data.get("source", "batch"),
                    "type": event_type,
                    "target": event_data.get("target", "unknown"),
                    "severity": severity,
                    "data": event_data.get("data", {}),
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
                        event_row["source"],
                        event_type,
                        event_row["target"],
                        severity,
                        sanitized_data,
                        event_data.get("related_incident_id"),
                        event_data.get("related_change_id"),
                        event_data.get("related_problem_id"),
                        event_data.get("parent_event_id"),
                        authenticated_as,
                        signature,
                    ),
                )

                event_ids.append(event_id)
                accepted += 1

                # Async processing for SIEM and SSE
                try:
                    ocsf_event = transform_to_ocsf(event_row)
                    asyncio.create_task(forward_to_siem(ocsf_event))
                    asyncio.create_task(publish(event_row))
                except Exception:
                    logger.debug("Async processing failed for event %s", event_id)

            except Exception as e:
                errors.append({"index": idx, "error": str(e)})
                rejected += 1

        await db.commit()

        return BatchEventResponse(
            total=len(events.events),
            accepted=accepted,
            rejected=rejected,
            event_ids=event_ids,
            errors=errors,
        )

    finally:
        await db.close()
