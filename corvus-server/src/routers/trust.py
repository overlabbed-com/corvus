"""Trust ledger API endpoints."""

from fastapi import APIRouter

from src.tasks.trust_ledger import get_all_tiers, get_trust_tier

router = APIRouter(prefix="/ops/trust", tags=["trust"])


@router.get("")
async def list_trust_ledger():
    """Get the full trust ledger — all action types with tiers and stats."""
    return await get_all_tiers()


@router.get("/{action_type:path}")
async def get_action_trust(action_type: str):
    """Get trust tier for a specific action type."""
    return await get_trust_tier(action_type)
