"""Shared in-memory metrics for background task self-timing.

Each background task records its execution duration and item count.
The metrics collector reads these values each cycle.
"""

import time
from contextlib import contextmanager

_task_timings: dict[str, list[float]] = {}
_task_counts: dict[str, list[int]] = {}


@contextmanager
def track_task(name: str, count: int = 0):
    """Context manager that records task execution duration.

    Usage:
        with track_task("change_expiry") as ctx:
            count = await expire_stale_changes()
            ctx["count"] = count
    """
    start = time.monotonic()
    holder = {"count": count}
    yield holder
    elapsed_ms = (time.monotonic() - start) * 1000
    _task_timings.setdefault(name, []).append(elapsed_ms)
    _task_counts.setdefault(name, []).append(holder["count"])


def get_task_stats() -> dict[str, dict]:
    """Return timing stats for all tasks and clear the buffers."""
    stats = {}
    for name in set(list(_task_timings.keys()) + list(_task_counts.keys())):
        timings = _task_timings.get(name, [])
        counts = _task_counts.get(name, [])
        if timings:
            sorted_t = sorted(timings)
            n = len(sorted_t)
            stats[name] = {
                "duration_ms_p50": sorted_t[n // 2],
                "duration_ms_p95": sorted_t[int(n * 0.95)] if n >= 20 else sorted_t[-1],
                "duration_ms_max": sorted_t[-1],
                "executions": n,
                "items_processed": sum(counts),
            }
        _task_timings.pop(name, None)
        _task_counts.pop(name, None)
    return stats


# SIEM forwarder latency buffer (separate from task timing)
_siem_latencies: list[float] = []


def record_siem_latency(duration_ms: float) -> None:
    _siem_latencies.append(duration_ms)


def get_siem_latency_stats() -> dict:
    """Return SIEM forwarding latency stats and clear buffer."""
    if not _siem_latencies:
        return {}
    sorted_l = sorted(_siem_latencies)
    n = len(sorted_l)
    stats = {
        "p50": sorted_l[n // 2],
        "p95": sorted_l[int(n * 0.95)] if n >= 20 else sorted_l[-1],
        "count": n,
    }
    _siem_latencies.clear()
    return stats
