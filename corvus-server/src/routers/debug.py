"""Story 3.4: Debug endpoints for system diagnostics.

Admin-only endpoints for debugging and monitoring Corvus state.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from src.event_bus import get_dropped_events_count, get_subscription_count
from src.middleware.auth import Role, get_auth
from src.siem.forwarder import get_dead_letters, get_forwarding_stats
from src.tasks.gap_detection import get_gap_summary

logger = logging.getLogger(__name__)

router = APIRouter(tags=["debug"])


@router.get("/debug/state")
async def debug_state(auth: dict = Depends(get_auth)):
    """Get full system state (admin only).

    Story 3.4: Comprehensive debugging endpoint.
    """
    # Check admin role
    if auth.get("role") != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        forwarding_stats = await get_forwarding_stats()
        dead_letters = await get_dead_letters()
        gaps = await get_gap_summary()
        return JSONResponse(
            content={
                "timestamp": datetime.now(UTC).isoformat(),
                "subscriptions": {
                    "active_count": get_subscription_count(),
                    "dropped_events": get_dropped_events_count(),
                },
                "siem": {
                    "forwarding_stats": forwarding_stats,
                    "dead_letter_count": len(dead_letters),
                },
                "gaps": gaps,
            }
        )
    except Exception as e:
        logger.error(f"Debug state failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Debug state failed: {str(e)}"
        ) from e


@router.get("/debug/memory")
async def debug_memory(auth: dict = Depends(get_auth)):
    """Get memory usage snapshot (admin only).

    Story 3.4: Memory diagnostics.
    """
    if auth.get("role") != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        import gc

        # Force garbage collection
        gc.collect()

        # Get basic memory info
        mem_info = {
            "timestamp": datetime.now(UTC).isoformat(),
            "gc_collections": gc.get_stats(),
            "object_count": len(gc.get_objects()),
        }

        return JSONResponse(content=mem_info)
    except Exception as e:
        logger.error(f"Memory debug failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory debug failed: {str(e)}")


@router.get("/debug/triage/in-progress")
async def debug_triage_in_progress(auth: dict = Depends(get_auth)):
    """Get active triage sessions (admin only).

    Story 3.4: Triage debugging.
    """
    if auth.get("role") != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Placeholder - would need to track active triages
    return JSONResponse(
        content={
            "timestamp": datetime.now(UTC).isoformat(),
            "active_triages": [],  # Would be populated from active triage tracking
            "note": "Active triage tracking not yet implemented",
        }
    )
