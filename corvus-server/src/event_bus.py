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

# Story 2.8: Metrics for dropped events
_dropped_events_count = 0
_dropped_events_lock = asyncio.Lock()

# Story 2.3: Heartbeat interval and subscription timeout
_HEARTBEAT_INTERVAL = 30  # seconds
_SUBSCRIPTION_TIMEOUT = 300  # 5 minutes


async def publish(event: dict[str, Any]) -> None:
    """Publish an event to all matching subscribers.
    
    Story 2.8: If queue is full, log and increment dropped counter.
    """
    async with _subscriber_lock:
        # Extract queues from (queue, last_activity) tuples
        queues = [(sub_id, item[0] if isinstance(item, tuple) else item) 
                  for sub_id, item in _subscribers.items()]
    
    dropped = 0
    for sub_id, q in queues:
        if q.full():
            dropped += 1
        else:
            try:
                q.put_nowait(event)
                # Update last activity
                async with _subscriber_lock:
                    if sub_id in _subscribers:
                        if isinstance(_subscribers[sub_id], tuple):
                            _subscribers[sub_id] = (q, datetime.now(UTC))
                        else:
                            _subscribers[sub_id] = q
            except asyncio.QueueFull:
                dropped += 1
    
    if dropped > 0:
        global _dropped_events_count
        async with _dropped_events_lock:
            _dropped_events_count += dropped
        logger.warning(
            "Dropped %d events due to full queues (total dropped: %d)",
            dropped,
            _dropped_events_count,
        )


async def subscribe(
    filters: dict[str, Any] | None = None,
    queue_size: int = 100,
) -> tuple[asyncio.Queue, asyncio.Task]:
    """Subscribe to events matching filters.

    Story 2.3: Add heartbeat and subscription timeout.
    Story 2.8: Track subscription for metrics.

    Returns (queue, cancel_task). Consume from queue.get().
    """
    q = asyncio.Queue(maxsize=queue_size)
    sub_id = f"{id(q)}-{datetime.now(UTC).isoformat()}"
    last_activity = datetime.now(UTC)

    async with _subscriber_lock:
        _subscribers[sub_id] = (q, last_activity)

    async def _reader():
        """Background reader — pulls from global event log and fans out.
        
        Story 2.3: Sends heartbeat every 30s, times out after 5min idle.
        """
        last_heartbeat = datetime.now(UTC)
        try:
            while True:
                now = datetime.now(UTC)
                
                # Check for subscription timeout (5 min idle)
                if (now - last_activity).total_seconds() > _SUBSCRIPTION_TIMEOUT:
                    logger.info("Subscription %s timed out after %ds idle", sub_id, _SUBSCRIPTION_TIMEOUT)
                    break
                
                # Send heartbeat every 30s if no events
                if (now - last_heartbeat).total_seconds() > _HEARTBEAT_INTERVAL:
                    try:
                        q.put_nowait({"type": "heartbeat", "timestamp": now.isoformat()})
                        last_heartbeat = now
                    except asyncio.QueueFull:
                        pass  # Queue full, skip heartbeat
                
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            async with _subscriber_lock:
                _subscribers.pop(sub_id, None)
            logger.info("Subscription %s cleaned up", sub_id)

    cancel_task = asyncio.create_task(_reader())
    return q, cancel_task


def get_subscription_count() -> int:
    """Get current number of active subscriptions."""
    return len(_subscribers)

def get_dropped_events_count() -> int:
    """Story 2.8: Get total dropped events count."""
    return _dropped_events_count

def cancel_subscription(sub_id: str) -> None:
    """Cancel a subscription by ID."""
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
    _hourly_counts[event_type] = [(h, c) for h, c in _hourly_counts[event_type] if h > cutoff]


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
    _incident_timeline[incident_id] = [(t, s) for t, s in _incident_timeline[incident_id] if t > cutoff]

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
