"""Layer 3: Inspected discovery from running containers.

Queries the admin-api /containers endpoint to get runtime state of all
containers across all hosts. Overlays this onto declared discovery for
drift detection and confidence upgrading.
"""

import logging

import httpx

from src.discovery.declared import DiscoveryResult

logger = logging.getLogger(__name__)


async def inspect_containers(admin_api_url: str, admin_api_token: str = "") -> DiscoveryResult:
    """Query admin-api for all running containers and return runtime state.

    Args:
        admin_api_url: Base URL of the admin-api (e.g., https://admin-api.example.com).
        admin_api_token: Optional Bearer token for authentication.

    Returns:
        DiscoveryResult with runtime service information.
        Empty result if admin-api is unreachable.
    """
    result = DiscoveryResult()
    url = f"{admin_api_url.rstrip('/')}/containers"

    headers = {}
    if admin_api_token:
        headers["Authorization"] = f"Bearer {admin_api_token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            containers = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Admin API returned %d: %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return result
    except Exception:
        logger.warning("Admin API unreachable at %s", url, exc_info=True)
        return result

    if not isinstance(containers, list):
        logger.warning("Unexpected admin API response format: %s", type(containers))
        return result

    for container in containers:
        if not isinstance(container, dict):
            continue

        name = container.get("name", container.get("Names", ""))
        # Strip leading slash if present (Docker API format)
        if isinstance(name, str) and name.startswith("/"):
            name = name[1:]
        if isinstance(name, list) and name:
            name = name[0].lstrip("/")

        if not name:
            continue

        status = container.get("status", container.get("State", ""))
        image = container.get("image", container.get("Image", ""))
        host = container.get("host", "")
        health = container.get("health", "")

        result.services.append(
            {
                "name": name,
                "host": host,
                "image": image,
                "status": status,
                "health": health,
                "service_type": "container",
                "stack": "",
            }
        )

    logger.info("Inspected %d running containers from admin-api", len(result.services))
    return result
