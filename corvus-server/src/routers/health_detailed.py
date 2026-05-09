"""Story 3.2: Enhanced health checks.

Provides detailed health and readiness endpoints for monitoring.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from src.config import CORVUS_DEV_MODE
from src.database import get_db
from src.event_bus import get_dropped_events_count, get_subscription_count
from src.graph import graph_available, graph_health
from src.siem.forwarder import get_forwarding_stats

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health/ready")
async def readiness_check():
    """Readiness probe - can the service handle requests?

    Story 3.2: Checks all critical dependencies.
    """
    checks = {
        "database": await check_database_health(),
        "graph": graph_available(),
        "timestamp": datetime.now(UTC).isoformat(),
    }

    all_healthy = all(
        [
            checks["database"]["healthy"],
            checks["graph"],  # Graph is optional
        ]
    )

    status = 200 if all_healthy else 503
    return JSONResponse(
        status_code=status,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
        },
    )


@router.get("/health/detailed")
async def detailed_health():
    """Detailed health diagnostics (admin only).

    Story 3.2: Comprehensive system state for debugging.
    """
    try:
        db_healthy, db_info = await _check_database_health_detailed()
        graph_avail = graph_available()
        graph_hlth = graph_health() if graph_avail else {"status": "unavailable"}
        siem_stats = await get_forwarding_stats()

        return JSONResponse(
            content={
                "status": "healthy" if db_healthy and graph_avail else "degraded",
                "database": {
                    "healthy": db_healthy,
                    **db_info,
                },
                "graph": {
                    "available": graph_avail,
                    **graph_hlth,
                },
                "subscriptions": {
                    "active_count": get_subscription_count(),
                    "dropped_events": get_dropped_events_count(),
                },
                "siem": siem_stats,
                "dev_mode": CORVUS_DEV_MODE,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Health check failed: {str(e)}"
        ) from e


async def check_database_health() -> dict:
    """Check database health."""
    try:
        db = await get_db()
        try:
            # Simple query to verify connectivity
            cursor = await db.execute("SELECT 1")
            result = await cursor.fetchone()

            if result and result[0] == 1:
                # Get table count for health info
                cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = await cursor.fetchall()

                return {
                    "healthy": True,
                    "tables": len(tables),
                    "message": "Database healthy",
                }
            else:
                return {
                    "healthy": False,
                    "message": "Database query returned unexpected result",
                }
        finally:
            await db.close()
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
            "message": "Database connection failed",
        }


async def _check_database_health_detailed() -> tuple[bool, dict]:
    """Check database health with detailed info."""
    result = await check_database_health()
    return result["healthy"], result
