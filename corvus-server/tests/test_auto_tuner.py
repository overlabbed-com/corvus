"""Auto-tuner tests -- dampening, safety rails, revert."""

import json

import pytest

from src.config import RuntimeConfig
from src.database import get_db
from src.tasks.auto_tuner import (
    TuningRule,
    compute_dampened_correction,
    evaluate_and_adjust,
    run_auto_tuner,
    should_revert,
)


def test_dampening_factor_decreases_with_adjustments():
    """Dampening factor decays exponentially."""
    f1 = compute_dampened_correction(100, adjustment_number=1, k=0.1)
    f5 = compute_dampened_correction(100, adjustment_number=5, k=0.1)
    f10 = compute_dampened_correction(100, adjustment_number=10, k=0.1)
    assert f1 > f5 > f10
    assert abs(f1 - 90.5) < 1  # ~90% of 100
    assert abs(f10 - 36.8) < 1  # ~37% of 100


def test_dampening_converges_toward_zero():
    """After many adjustments, correction is near zero."""
    f30 = compute_dampened_correction(100, adjustment_number=30, k=0.1)
    assert f30 < 6  # < 5% of original


@pytest.mark.asyncio
async def test_evaluate_and_adjust_applies_correction(client):
    """When metric crosses threshold, adjustment is applied."""
    RuntimeConfig.reset()
    RuntimeConfig.register_default("test.tunable", 300, min_val=30, max_val=3600)

    rule = TuningRule(
        parameter="test.tunable",
        trigger_metric="test_timeout_rate",
        threshold=15.0,
        direction="increase",
        correction_factor=0.5,
    )

    metrics = {"test_timeout_rate": 25.0}  # exceeds 15% threshold
    adjusted = await evaluate_and_adjust(rule, metrics)
    assert adjusted is True
    assert RuntimeConfig.get("test.tunable") > 300  # should have increased

    # Verify adjustment logged
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ops_metric_adjustments WHERE parameter = 'test.tunable'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert float(row["dampening_factor"]) > 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_cooldown_prevents_rapid_adjustment(client):
    """Parameter is not adjusted again within cooldown period."""
    RuntimeConfig.reset()
    RuntimeConfig.register_default("test.cooldown", 100, min_val=10, max_val=1000)

    rule = TuningRule(
        parameter="test.cooldown",
        trigger_metric="test_metric",
        threshold=10.0,
        direction="increase",
        correction_factor=0.3,
    )

    # First adjustment
    await evaluate_and_adjust(rule, {"test_metric": 20.0})
    val_after_first = RuntimeConfig.get("test.cooldown")

    # Immediate second attempt -- should be skipped (cooldown)
    await evaluate_and_adjust(rule, {"test_metric": 25.0})
    val_after_second = RuntimeConfig.get("test.cooldown")
    assert val_after_first == val_after_second  # unchanged


@pytest.mark.asyncio
async def test_revert_on_worsening(client):
    """Auto-revert if metric worsens after adjustment."""
    result = should_revert(
        trigger_values_after=[20.0, 25.0],  # worsening over 2 cycles
        trigger_value_before=15.0,
        direction="increase",
    )
    assert result is True


@pytest.mark.asyncio
async def test_run_auto_tuner_reverts_worsening_adjustment(client):
    """Full integration: run_auto_tuner reverts a parameter when its trigger metric worsens."""
    import uuid

    RuntimeConfig.reset()
    RuntimeConfig.register_default("step_timeout.default", 300, min_val=30, max_val=3600)

    # Simulate a past adjustment (not in cooldown -- use old timestamp)
    adj_id = f"ADJ-{uuid.uuid4().hex[:8].upper()}"
    adj_time = "2020-01-01T00:00:00+00:00"
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO ops_metric_adjustments "
            "(id, timestamp, parameter, old_value, new_value, trigger_metric, "
            "trigger_value, trigger_threshold, adjustment_number, dampening_factor, reasoning) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                adj_id,
                adj_time,
                "step_timeout.default",
                "300",
                "350",
                "timeout_rate",
                20.0,
                15.0,
                1,
                1.0,
                "test adjustment",
            ),
        )
        await db.commit()
    finally:
        await db.close()

    # Override the value to mimic the adjustment having been applied
    RuntimeConfig.set("step_timeout.default", 350)

    # Insert 2 metric snapshots AFTER the adjustment with worsening trigger values
    db = await get_db()
    try:
        for i, trigger_val in enumerate([25.0, 30.0]):
            snap_id = f"SNAP-{uuid.uuid4().hex[:8].upper()}"
            snap_time = f"2020-01-01T01:0{i}:00+00:00"
            metrics_json = json.dumps({"timeout_rate": trigger_val})
            await db.execute(
                "INSERT INTO ops_metrics_snapshots "
                "(id, timestamp, period_start, period_end, tier, metrics) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (snap_id, snap_time, snap_time, snap_time, "throughput", metrics_json),
            )
        await db.commit()
    finally:
        await db.close()

    # Run auto-tuner with metrics BELOW threshold so no new adjustment fires
    await run_auto_tuner({"throughput": {"timeout_rate": 5.0}})

    # Parameter should have been reverted to default
    assert RuntimeConfig.get("step_timeout.default") == 300

    # Adjustment row should be marked as reverted
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT reverted, reverted_at, revert_reason "
            "FROM ops_metric_adjustments WHERE id = ?",
            (adj_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["reverted"] == 1
        assert row["reverted_at"] is not None
        assert "worsened" in row["revert_reason"]
    finally:
        await db.close()
