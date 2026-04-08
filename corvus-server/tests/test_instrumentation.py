"""Instrumentation tests -- task timing and SIEM latency."""

import time

from src.tasks.task_metrics import (
    get_siem_latency_stats,
    get_task_stats,
    record_siem_latency,
    track_task,
)


def test_track_task_records_duration():
    """Task timing records execution duration."""
    get_task_stats()  # clear
    with track_task("test_task") as ctx:
        time.sleep(0.01)  # 10ms
        ctx["count"] = 5
    stats = get_task_stats()
    assert "test_task" in stats
    assert stats["test_task"]["duration_ms_p50"] >= 5  # at least 5ms
    assert stats["test_task"]["items_processed"] == 5


def test_get_task_stats_clears_buffer():
    """Stats buffer is cleared after reading."""
    get_task_stats()  # clear
    with track_task("ephemeral"):
        pass
    get_task_stats()  # read and clear
    stats = get_task_stats()  # should be empty
    assert "ephemeral" not in stats


def test_siem_latency_tracking():
    """SIEM latency recording and percentile computation."""
    get_siem_latency_stats()  # clear
    for ms in [10, 20, 30, 40, 50]:
        record_siem_latency(ms)
    stats = get_siem_latency_stats()
    assert stats["p50"] == 30
    assert stats["count"] == 5


def test_siem_latency_clears_buffer():
    """SIEM latency buffer cleared after reading."""
    get_siem_latency_stats()  # clear
    record_siem_latency(100)
    get_siem_latency_stats()
    assert get_siem_latency_stats() == {}
