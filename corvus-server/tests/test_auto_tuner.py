"""Auto-tuner tests -- dampening, safety rails, revert."""

import json
import math
from datetime import UTC, datetime

import pytest

from src.config import RuntimeConfig
from src.database import get_db
from src.tasks.auto_tuner import (
    TuningRule,
    compute_dampened_correction,
    evaluate_and_adjust,
    should_revert,
)


@pytest.fixture(autouse=True)
def _restore_runtime_config():
    """Save and restore RuntimeConfig state so reset() in tests doesn't leak."""
    saved_values = dict(RuntimeConfig._values)
    saved_defaults = dict(RuntimeConfig._defaults)
    saved_bounds = dict(RuntimeConfig._bounds)
    yield
    RuntimeConfig._values = saved_values
    RuntimeConfig._defaults = saved_defaults
    RuntimeConfig._bounds = saved_bounds


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
