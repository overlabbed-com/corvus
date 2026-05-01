"""Story 3.1: Prometheus metrics endpoint.

Provides /metrics endpoint for Prometheus scraping.
"""

from fastapi import APIRouter

from src.metrics import PROMETHEUS_AVAILABLE, get_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def get_prometheus_metrics():
    """Get metrics in Prometheus format.

    Story 3.1: Exposes all Corvus metrics for Prometheus scraping.
    """
    from fastapi.responses import Response

    if not PROMETHEUS_AVAILABLE:
        return Response(
            content="# Prometheus metrics not available (prometheus_client not installed)\n", media_type="text/plain"
        )

    metrics = get_metrics()
    return Response(content=metrics.decode("utf-8"), media_type="text/plain; version=0.0.4")
