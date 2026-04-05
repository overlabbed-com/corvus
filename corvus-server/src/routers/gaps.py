"""Gap sweep API endpoints."""

from fastapi import APIRouter

from src.tasks.gap_sweep import run_gap_sweep

router = APIRouter(prefix="/ops/gaps", tags=["gaps"])


@router.post("/sweep")
async def trigger_gap_sweep():
    """Trigger an on-demand gap sweep."""
    return await run_gap_sweep()
