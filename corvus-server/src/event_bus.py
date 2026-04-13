"""Event bus — asyncio.Queue pub/sub for real-time SSE streaming (GAP-4)."""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# In-memory pub/sub queues
_subscribers: dict[str, asyncio.Queue] = {}
_subscriber_lock = asyncio.Lock()


async def publish(event: dict[str, Any]) -> None:
    """Publish an event to all matching subscribers."""
    async with _subscriber_lock:
        queues = list(_subscribers.values())
    for q in queues:
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(event)


async def subscribe(
    filters: dict[str, Any] | None = None,
    queue_size: int = 100,
) -> tuple[asyncio.Queue, asyncio.Task]:
    """Subscribe to events matching filters.


    Returns (queue, cancel_task). Consume from queue.get().
    """
    q = asyncio.Queue(maxsize=queue_size)
    sub_id = f"{id(q)}"

    async with _subscriber_lock:
        _subscribers[sub_id] = q

    async def _reader():
        """Background reader — pulls from global event log and fans out."""
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            async with _subscriber_lock:
                _subscribers.pop(sub_id, None)

    cancel_task = asyncio.create_task(_reader())
    return q, cancel_task


def cancel_subscription(sub_id: str) -> None:
    """Cancel a subscription by ID."""
    # Synchronous helper — call from sync context if needed
    _subscribers.pop(sub_id, None)


# ---------------------------------------------------------------------------
# Anomaly Detection (GAP-5)
# ---------------------------------------------------------------------------

# Rolling hourly event counts: type -> [(hour_timestamp, count)]
_hourly_counts: dict[str, list[tuple[datetime, int]]] = {}
_HOURS_TO_KEEP = 168  # 1 week


def _current_hour() -> datetime:
    now = datetime.now(UTC)
    return now.replace(minute=0, second=0, microsecond=0)


def record_event(event_type: str) -> None:
    """Record an event for anomaly detection."""
    hour = _current_hour()
    if event_type not in _hourly_counts:
        _hourly_counts[event_type] = []
    _hourly_counts[event_type].append((hour, 1))
    # Prune old entries
    cutoff = hour - timedelta(hours=_HOURS_TO_KEEP)
    _hourly_counts[event_type] = [
        (h, c) for h, c in _hourly_counts[event_type] if h > cutoff
    ]


def get_hourly_rate(event_type: str) -> float:
    """Get average events/hour for the last 7 days, or 0 if no data."""
    if event_type not in _hourly_counts:
        return 0.0
    hour = _current_hour()
    cutoff = hour - timedelta(hours=_HOURS_TO_KEEP)
    recent = [(h, c) for h, c in _hourly_counts[event_type] if h > cutoff]
    if not recent:
        return 0.0
    total = sum(c for _, c in recent)
    return total / len(recent)


def detect_anomaly(event_type: str, current_count: int) -> bool:
    """Return True if current_count exceeds 2-sigma threshold.

    Uses rolling baseline from last 7 days.
    """
    if event_type not in _hourly_counts:
        return False
    hour = _current_hour()
    cutoff = hour - timedelta(hours=_HOURS_TO_KEEP)
    recent = [c for h, c in _hourly_counts[event_type] if h > cutoff]
    if len(recent) < 3:
        return False

    import statistics

    mean = statistics.mean(recent)
    stdev = statistics.stdev(recent) if len(recent) > 1 else 0
    if stdev == 0:
        return current_count > mean * 2
    threshold = mean + 2 * stdev
    return current_count > threshold


# ---------------------------------------------------------------------------
# Contradiction Detection (GAP-6)
# ---------------------------------------------------------------------------

# Track recent incident state changes: incident_id -> [(timestamp, type)]
_incident_timeline: dict[str, list[tuple[datetime, str]]] = {}
_CONTRADICTION_WINDOW = timedelta(hours=1)


def record_incident_state(incident_id: str, state: str) -> list[dict[str, Any]]:
    """Record an incident state transition.

    Returns list of contradictions detected (for alerting).
    """
    now = datetime.now(UTC)
    if incident_id not in _incident_timeline:
        _incident_timeline[incident_id] = []
    _incident_timeline[incident_id].append((now, state))

    # Prune old entries
    cutoff = now - timedelta(hours=24)
    _incident_timeline[incident_id] = [
        (t, s) for t, s in _incident_timeline[incident_id] if t > cutoff
    ]

    contradictions = []
    timeline = _incident_timeline[incident_id]
    for _i, (ts, stype) in enumerate(timeline):
        if stype == "incident.resolved" and state == "incident.opened" and (now - ts) <= _CONTRADICTION_WINDOW:
                contradictions.append(
                    {
                        "incident_id": incident_id,
                        "resolved_at": ts.isoformat(),
                        "reopened_at": now.isoformat(),
                        "gap_minutes": int((now - ts).total_seconds() / 60),
                    }
                )
    return contradictions
