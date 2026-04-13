"""SIEM forwarder — config-driven adapter selection and event forwarding.

Supports multiple SIEM backends via the adapter pattern:
- splunk: Splunk HEC
- sentinel: Azure Sentinel / Log Analytics
- chronicle: Google Chronicle (native OCSF)
- elastic: Elasticsearch / OpenSearch

Config: CORVUS_SIEM_TYPE selects the adapter. Each adapter reads its own
env vars for authentication. Multiple adapters can be active (comma-separated).

GAP-7: SIEM Health Monitoring — tracks consecutive failures and logs
critical alert after 3 consecutive failures.
"""

import json
import logging
import os
from typing import Any

from src.sanitizer import sanitize
from src.siem.base import SIEMAdapter

logger = logging.getLogger(__name__)

# Active adapters (initialized on first use)
_adapters: list[SIEMAdapter] | None = None

# GAP-7: SIEM health tracking
_consecutive_failures: int = 0
_MAX_CONSECUTIVE_FAILURES = 3  # Alert threshold


def _init_adapters() -> list[SIEMAdapter]:
    """Initialize SIEM adapters from environment config."""
    siem_types = os.getenv("CORVUS_SIEM_TYPE", "splunk").split(",")
    adapters: list[SIEMAdapter] = []

    for siem_type in siem_types:
        siem_type = siem_type.strip().lower()

        if siem_type == "splunk":
            from src.siem.splunk import SplunkAdapter

            adapter = SplunkAdapter(
                url=os.getenv("CORVUS_SIEM_URL", ""),
                token=os.getenv("CORVUS_SIEM_TOKEN", ""),
                index=os.getenv("CORVUS_SIEM_INDEX", "corvus"),
                verify_tls=os.getenv("CORVUS_SIEM_VERIFY_TLS", "true").lower() == "true",
            )
        elif siem_type == "sentinel":
            from src.siem.sentinel import SentinelAdapter

            adapter = SentinelAdapter(
                workspace_id=os.getenv("CORVUS_SENTINEL_WORKSPACE_ID", ""),
                shared_key=os.getenv("CORVUS_SENTINEL_SHARED_KEY", ""),
                log_type=os.getenv("CORVUS_SENTINEL_LOG_TYPE", "CorvusOCSF"),
            )
        elif siem_type == "chronicle":
            from src.siem.chronicle import ChronicleAdapter

            adapter = ChronicleAdapter(
                api_key=os.getenv("CORVUS_CHRONICLE_API_KEY", ""),
                customer_id=os.getenv("CORVUS_CHRONICLE_CUSTOMER_ID", ""),
                region=os.getenv("CORVUS_CHRONICLE_REGION", "us"),
            )
        elif siem_type == "elastic":
            from src.siem.elastic import ElasticAdapter

            adapter = ElasticAdapter(
                url=os.getenv("CORVUS_ELASTIC_URL", ""),
                api_key=os.getenv("CORVUS_ELASTIC_API_KEY", ""),
                index_prefix=os.getenv("CORVUS_ELASTIC_INDEX_PREFIX", "corvus-ocsf"),
                username=os.getenv("CORVUS_ELASTIC_USERNAME", ""),
                password=os.getenv("CORVUS_ELASTIC_PASSWORD", ""),
            )
        else:
            logger.warning("Unknown SIEM type: %s", siem_type)
            continue

        if adapter.is_configured():
            adapters.append(adapter)
            logger.info("SIEM adapter configured: %s", adapter.name)
        else:
            logger.info("SIEM adapter %s not configured (missing credentials)", adapter.name)

    return adapters


def _get_adapters() -> list[SIEMAdapter]:
    """Get or initialize adapters."""
    global _adapters
    if _adapters is None:
        _adapters = _init_adapters()
    return _adapters


async def forward_to_siem(ocsf_event: dict[str, Any]) -> bool:
    """Forward an OCSF event to all configured SIEM backends.

    Returns True if forwarded to at least one backend successfully.
    """
    adapters = _get_adapters()
    if not adapters:
        return False

    # Sanitize event data before forwarding
    ocsf_event = json.loads(sanitize(json.dumps(ocsf_event, default=str)))

    any_success = False
    global _consecutive_failures
    for adapter in adapters:
        if await adapter.forward(ocsf_event):
            any_success = True
            _consecutive_failures = 0  # Reset on success
        else:
            _consecutive_failures += 1
            if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.critical(
                    "SIEM forwarding health alert: %d consecutive failures. "
                    "SIEM may be down or unreachable. Check CORVUS_SIEM_* configuration.",
                    _consecutive_failures,
                )
                _consecutive_failures = 0  # Reset after alert (avoid spam)

    return any_success


def get_forwarding_stats() -> dict[str, Any]:
    """Get SIEM forwarding stats for /ops/metrics."""
    adapters = _get_adapters()
    if not adapters:
        return {
            "adapter": "none",
            "forwarded": 0,
            "failed": 0,
            "retries": 0,
            "dead_letter_count": 0,
            "siem_configured": False,
        }

    if len(adapters) == 1:
        stats = adapters[0].get_stats()
        stats["siem_configured"] = True
        return stats

    # Multiple adapters — aggregate
    total = {"forwarded": 0, "failed": 0, "retries": 0, "dead_letter_count": 0}
    per_adapter = {}
    for adapter in adapters:
        stats = adapter.get_stats()
        total["forwarded"] += stats["forwarded"]
        total["failed"] += stats["failed"]
        total["retries"] += stats["retries"]
        total["dead_letter_count"] += stats["dead_letter_count"]
        per_adapter[adapter.name] = stats

    return {
        "adapter": "multi",
        "adapters": per_adapter,
        **total,
        "siem_configured": True,
    }


def get_dead_letters() -> list[dict[str, Any]]:
    """Get dead letter queue contents from all adapters."""
    result = []
    for adapter in _get_adapters():
        result.extend(adapter.get_dead_letters())
    return result
