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

Story 1.2: Reliable SIEM forwarding with retry + exponential backoff
and dead-letter queue for failed events.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from src.sanitizer import sanitize
from src.siem.base import SIEMAdapter

logger = logging.getLogger(__name__)

# Active adapters (initialized on first use)
_adapters: list[SIEMAdapter] | None = None

# GAP-7: SIEM health tracking (now with asyncio.Lock for thread safety)
_failure_lock = asyncio.Lock()
_failure_counts: dict[str, int] = {}
_MAX_CONSECUTIVE_FAILURES = 3  # Alert threshold

# Story 1.2: Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0


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


async def _store_dead_letter(
    event_id: str,
    event_type: str | None,
    event_data: dict[str, Any],
    error: str,
    adapter_name: str,
) -> None:
    """Store a failed event in the dead-letter queue table."""
    try:
        from src.database import get_db

        db = await get_db()
        try:
            now = datetime.now(UTC).isoformat()
            dl_id = f"DL-{uuid.uuid4().hex[:8].upper()}"

            await db.execute(
                """INSERT INTO ops_siem_dead_letter
                   (id, event_id, event_type, event_data, error, attempted_at, attempt_count, last_adapter)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    dl_id,
                    event_id,
                    event_type,
                    json.dumps(event_data),
                    error,
                    now,
                    adapter_name,
                ),
            )
            await db.commit()
            logger.info("Stored event %s in dead-letter queue: %s", event_id, error)
        finally:
            await db.close()
    except Exception:
        logger.exception("Failed to store event in dead-letter queue: %s", event_id)


async def _forward_to_adapter_with_retry(
    adapter: SIEMAdapter, ocsf_event: dict[str, Any], event_id: str
) -> tuple[bool, str | None]:
    """Forward to a single adapter with retry and exponential backoff.

    Returns (success, error_message).
    """
    last_error = None
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if await adapter.forward(ocsf_event):
                return (True, None)
        except Exception as e:
            last_error = str(e)
            logger.warning(
                "SIEM forward attempt %d/%d failed for %s: %s",
                attempt,
                MAX_RETRIES,
                event_id,
                last_error,
            )

        # Exponential backoff before retry (not on last attempt)
        if attempt < MAX_RETRIES:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    return (False, last_error)


async def forward_to_siem(ocsf_event: dict[str, Any]) -> bool:
    """Forward an OCSF event to all configured SIEM backends.

    Story 1.2: Uses retry with exponential backoff. Failed events
    are stored in the dead-letter queue.

    Returns True if forwarded to at least one backend successfully.
    """
    adapters = _get_adapters()
    if not adapters:
        logger.warning("No SIEM adapters configured, skipping forward")
        return False

    # Sanitize event data before forwarding
    ocsf_event = json.loads(sanitize(json.dumps(ocsf_event, default=str)))
    event_id = ocsf_event.get("uid", "unknown")
    event_type = ocsf_event.get("class_name", None)

    any_success = False

    async with _failure_lock:
        for adapter in adapters:
            success, error = await _forward_to_adapter_with_retry(adapter, ocsf_event, event_id)

            if success:
                any_success = True
                # Reset failure count for this adapter on success
                _failure_counts[adapter.name] = 0
            else:
                # Increment failure count for this adapter
                _failure_counts[adapter.name] = _failure_counts.get(adapter.name, 0) + 1
                total_failures = _failure_counts[adapter.name]

                if total_failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.critical(
                        "SIEM forwarding health alert: %d consecutive failures on %s. "
                        "SIEM may be down or unreachable. Check CORVUS_SIEM_* configuration.",
                        total_failures,
                        adapter.name,
                    )
                    _failure_counts[adapter.name] = 0  # Reset after alert

                # Story 1.2: Store failed event in dead-letter queue
                if error:
                    await _store_dead_letter(event_id, event_type, ocsf_event, error, adapter.name)

    return any_success


async def get_forwarding_stats() -> dict[str, Any]:
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

    # Get dead-letter count from database
    dl_count = 0
    try:
        from src.database import get_db

        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM ops_siem_dead_letter WHERE resolved_at IS NULL"
            )
            row = await cursor.fetchone()
            dl_count = row["cnt"] if row else 0
        finally:
            await db.close()
    except Exception:
        dl_count = 0

    if len(adapters) == 1:
        stats = adapters[0].get_stats()
        stats["siem_configured"] = True
        stats["dead_letter_count"] = dl_count
        return stats

    # Multiple adapters — aggregate
    total = {"forwarded": 0, "failed": 0, "retries": 0, "dead_letter_count": dl_count}
    per_adapter = {}
    for adapter in adapters:
        stats = adapter.get_stats()
        total["forwarded"] += stats["forwarded"]
        total["failed"] += stats["failed"]
        total["retries"] += stats["retries"]
        per_adapter[adapter.name] = stats

    return {
        "adapter": "multi",
        "adapters": per_adapter,
        **total,
        "siem_configured": True,
    }


async def get_dead_letters(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Get dead letter queue contents from database.

    Story 1.2: Dead letters are now stored in the database for durability.
    """
    try:
        from src.database import get_db

        db = await get_db()
        try:
            cursor = await db.execute(
                """SELECT * FROM ops_siem_dead_letter
                   WHERE resolved_at IS NULL
                   ORDER BY attempted_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                result.append({
                    "id": row["id"],
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "event_data": json.loads(row["event_data"]),
                    "error": row["error"],
                    "attempted_at": row["attempted_at"],
                    "attempt_count": row["attempt_count"],
                    "last_adapter": row["last_adapter"],
                })
            return result
        finally:
            await db.close()
    except Exception:
        logger.exception("Failed to fetch dead letters from database")
        return []


async def resolve_dead_letter(dl_id: str, resolved_by: str | None = None) -> bool:
    """Mark a dead-letter entry as resolved."""
    try:
        from src.database import get_db

        db = await get_db()
        try:
            now = datetime.now(UTC).isoformat()
            await db.execute(
                "UPDATE ops_siem_dead_letter SET resolved_at = ?, resolved_by = ? WHERE id = ?",
                (now, resolved_by or "system", dl_id),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception:
        logger.exception("Failed to resolve dead letter: %s", dl_id)
        return False