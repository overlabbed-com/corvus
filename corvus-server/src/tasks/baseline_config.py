"""Story 2.7: Configurable resolution baselines.

Instead of hardcoded RESOLUTION_BASELINES, fetch from CMDB or use
auto-tuned values from historical data.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default baselines (fallback if CMDB not available)
DEFAULT_BASELINES = {
    "inference": 15,
    "database": 30,
    "proxy": 10,
    "mcp_bridge": 5,
    "secrets": 60,
    "iot_gateway": 20,
    "home_automation": 15,
    "media": 10,
    "monitoring": 20,
    "automation": 15,
    "dns": 30,
    "utility": 5,
}

DEFAULT_BASELINE = 20  # minutes


async def get_resolution_baseline(service_type: str | None) -> int:
    """Get resolution baseline for a service type.
    
    Story 2.7: Try to fetch from CMDB first, fall back to defaults.
    
    Args:
        service_type: The service type to get baseline for
        
    Returns:
        Baseline resolution time in minutes
    """
    if not service_type:
        return DEFAULT_BASELINE
    
    # Try to fetch from CMDB (if available)
    try:
        from src.database import get_db
        
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT baseline_behavior FROM ops_cmdb WHERE name = ?",
                (service_type,)
            )
            row = await cursor.fetchone()
            
            if row and row["baseline_behavior"]:
                import json
                baseline_data = json.loads(row["baseline_behavior"])
                if "resolution_minutes" in baseline_data:
                    return baseline_data["resolution_minutes"]
        finally:
            await db.close()
    except Exception as e:
        logger.debug(f"Could not fetch baseline from CMDB for {service_type}: {e}")
    
    # Fall back to defaults
    return DEFAULT_BASELINES.get(service_type, DEFAULT_BASELINE)


async def update_service_baseline(service_name: str, resolution_minutes: int) -> bool:
    """Update the resolution baseline for a service.
    
    Story 2.7: Store baseline in CMDB for future use.
    
    Args:
        service_name: Name of the service
        resolution_minutes: New baseline resolution time
        
    Returns:
        True if updated successfully
    """
    try:
        from src.database import get_db
        import json
        
        db = await get_db()
        try:
            # Get current baseline_behavior
            cursor = await db.execute(
                "SELECT baseline_behavior FROM ops_cmdb WHERE name = ?",
                (service_name,)
            )
            row = await cursor.fetchone()
            
            if row:
                baseline_data = json.loads(row["baseline_behavior"] or "{}")
                baseline_data["resolution_minutes"] = resolution_minutes
                
                await db.execute(
                    "UPDATE ops_cmdb SET baseline_behavior = ? WHERE name = ?",
                    (json.dumps(baseline_data), service_name),
                )
                await db.commit()
                logger.info(f"Updated baseline for {service_name} to {resolution_minutes}min")
                return True
            else:
                logger.warning(f"Service {service_name} not found in CMDB")
                return False
        finally:
            await db.close()
    except Exception as e:
        logger.error(f"Failed to update baseline for {service_name}: {e}")
        return False
