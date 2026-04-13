"""Auto-tuning engine with exponential dampening.

Reads operational metrics computed by the collector, evaluates them against
threshold-based tuning rules, and adjusts RuntimeConfig parameters with
exponentially dampened corrections.

Key properties:
- correction * e^(-k * n): early adjustments are bold (~90%), later ones
  converge toward zero (< 5% after 30 adjustments).
- 45-minute cooldown prevents oscillation (3 collector cycles).
- Bounds clamping via RuntimeConfig.set() prevents extreme values.
- should_revert() detects worsening trends for rollback.
"""

import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.config import RuntimeConfig
from src.database import get_db

logger = logging.getLogger(__name__)

# Cooldown: 3 collector cycles * 15 min = 45 min
COOLDOWN_MINUTES = 45


@dataclass
class TuningRule:
    """Defines how a metric triggers a parameter adjustment."""

    parameter: str  # RuntimeConfig key
    trigger_metric: str  # metric key to watch
    threshold: float  # trigger when metric exceeds this
    direction: str  # "increase" or "decrease" the parameter
    correction_factor: float  # fraction of distance to apply (0-1)


def compute_dampened_correction(
    raw_correction: float, adjustment_number: int, k: float = 0.1
) -> float:
    """Apply exponential dampening: correction * e^(-k * n)."""
    return raw_correction * math.exp(-k * adjustment_number)


def should_revert(
    trigger_values_after: list[float],
    trigger_value_before: float,
    direction: str,
) -> bool:
    """Return True if the metric worsened for 2 consecutive cycles after adjustment.

    "Worsened" for "increase" direction: trigger values went up (the metric we
    were trying to reduce by increasing the parameter actually got worse).
    "Worsened" for "decrease" direction: trigger values went down.
    """
    if len(trigger_values_after) < 2:
        return False

    last_two = trigger_values_after[-2:]

    if direction == "increase":
        # We increased the parameter to reduce the metric; if metric rose, it worsened
        return all(v > trigger_value_before for v in last_two)
    else:
        # We decreased the parameter to reduce the metric; if metric dropped, it worsened
        return all(v < trigger_value_before for v in last_two)


async def _get_adjustment_count(parameter: str) -> int:
    """Count previous adjustments for this parameter (for dampening)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_metric_adjustments WHERE parameter = ?",
            (parameter,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0
    finally:
        await db.close()


async def _is_in_cooldown(parameter: str) -> bool:
    """Check if the parameter was adjusted within the cooldown window."""
    cutoff = (datetime.now(UTC) - timedelta(minutes=COOLDOWN_MINUTES)).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT timestamp FROM ops_metric_adjustments "
            "WHERE parameter = ? AND timestamp > ? ORDER BY timestamp DESC LIMIT 1",
            (parameter, cutoff),
        )
        row = await cursor.fetchone()
        return row is not None
    finally:
        await db.close()


async def _log_adjustment(
    parameter: str,
    old_value: float,
    new_value: float,
    trigger_metric: str,
    trigger_value: float,
    trigger_threshold: float,
    adjustment_number: int,
    dampening_factor: float,
    reasoning: str,
) -> None:
    """Record an adjustment in the ops_metric_adjustments table."""
    adj_id = f"ADJ-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(UTC).isoformat()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO ops_metric_adjustments "
            "(id, timestamp, parameter, old_value, new_value, trigger_metric, "
            "trigger_value, trigger_threshold, adjustment_number, dampening_factor, reasoning) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                adj_id,
                now,
                parameter,
                str(old_value),
                str(new_value),
                trigger_metric,
                trigger_value,
                trigger_threshold,
                adjustment_number,
                dampening_factor,
                reasoning,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def evaluate_and_adjust(rule: TuningRule, metrics: dict) -> bool:
    """Evaluate a single tuning rule against current metrics.

    Returns True if an adjustment was applied, False otherwise.
    """
    # Check if trigger metric exists
    trigger_value = metrics.get(rule.trigger_metric)
    if trigger_value is None:
        return False

    # Check if metric exceeds threshold
    if trigger_value <= rule.threshold:
        return False

    # Check cooldown
    if await _is_in_cooldown(rule.parameter):
        logger.debug(
            "Skipping %s adjustment -- cooldown active", rule.parameter
        )
        return False

    # Get current value and adjustment count
    current_value = RuntimeConfig.get(rule.parameter)
    if not isinstance(current_value, (int, float)):
        logger.warning("Cannot auto-tune non-numeric parameter: %s", rule.parameter)
        return False

    adjustment_count = await _get_adjustment_count(rule.parameter)

    # Compute raw correction: proportional to how far metric exceeds threshold
    raw_correction = (
        current_value * rule.correction_factor * (trigger_value - rule.threshold) / rule.threshold
    )

    # Apply dampening
    dampening_factor = math.exp(-0.1 * adjustment_count)
    dampened = compute_dampened_correction(raw_correction, adjustment_count)

    # Apply direction
    new_value = current_value + dampened if rule.direction == "increase" else current_value - dampened

    # Preserve type (int stays int)
    if isinstance(current_value, int):
        new_value = int(round(new_value))

    old_value = current_value
    RuntimeConfig.set(rule.parameter, new_value)
    actual_new = RuntimeConfig.get(rule.parameter)

    reasoning = (
        f"{rule.trigger_metric}={trigger_value:.1f} exceeded threshold={rule.threshold:.1f}; "
        f"raw_correction={raw_correction:.2f}, dampened={dampened:.2f} "
        f"(n={adjustment_count}, factor={dampening_factor:.3f}); "
        f"{rule.direction} {rule.parameter}: {old_value} -> {actual_new}"
    )

    await _log_adjustment(
        parameter=rule.parameter,
        old_value=old_value,
        new_value=actual_new,
        trigger_metric=rule.trigger_metric,
        trigger_value=trigger_value,
        trigger_threshold=rule.threshold,
        adjustment_number=adjustment_count + 1,
        dampening_factor=dampening_factor,
        reasoning=reasoning,
    )

    logger.info("Auto-tuner: %s", reasoning)
    return True


# The 6 operational tuning rules
TUNING_RULES = [
    TuningRule("step_timeout.default", "timeout_rate", 15.0, "increase", 0.5),
    TuningRule("step_timeout.reaper_interval", "timeout_rate", 15.0, "decrease", 0.3),
    TuningRule("change_expiry.hours", "change_lead_time.p95", 14400, "increase", 0.2),
    TuningRule("trust.promotion_threshold", "rollback_rate", 20.0, "increase", 0.1),
    TuningRule("trust.min_executions", "rollback_rate", 20.0, "increase", 0.2),
    TuningRule("triage.confidence_threshold", "escalation_rate", 30.0, "decrease", 0.15),
]


async def _check_and_revert(rules_by_param: dict[str, TuningRule]) -> int:
    """Check recent adjustments for worsening metrics and revert if needed.

    Returns count of reverts applied.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, parameter, old_value, trigger_metric, trigger_value, "
            "timestamp FROM ops_metric_adjustments "
            "WHERE reverted = 0 ORDER BY timestamp DESC",
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    # Deduplicate: only check the most recent non-reverted adjustment per parameter
    seen_params: set[str] = set()
    candidates = []
    for row in rows:
        if row["parameter"] not in seen_params:
            seen_params.add(row["parameter"])
            candidates.append(row)

    reverts = 0
    for row in candidates:
        param = row["parameter"]
        rule = rules_by_param.get(param)
        if not rule:
            continue

        adj_time = row["timestamp"]
        trigger_before = row["trigger_value"]

        # Get metric snapshots taken after this adjustment (last 2 cycles)
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT metrics FROM ops_metrics_snapshots "
                "WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 2",
                (adj_time,),
            )
            snap_rows = await cursor.fetchall()
        finally:
            await db.close()

        if len(snap_rows) < 2:
            continue

        # Extract trigger metric values from snapshots
        trigger_values_after: list[float] = []
        for snap_row in reversed(snap_rows):  # oldest first
            snap_metrics = json.loads(snap_row["metrics"])
            # Check flat key and percentile sub-keys
            val = snap_metrics.get(rule.trigger_metric)
            if val is None:
                # Try as a percentile metric (e.g. change_lead_time.p95)
                parts = rule.trigger_metric.rsplit(".", 1)
                if len(parts) == 2:
                    parent = snap_metrics.get(parts[0])
                    if isinstance(parent, dict):
                        val = parent.get(parts[1])
            if isinstance(val, (int, float)):
                trigger_values_after.append(float(val))

        if should_revert(trigger_values_after, trigger_before, rule.direction):
            RuntimeConfig.revert(param)
            reverted_value = RuntimeConfig.get(param)
            now = datetime.now(UTC).isoformat()
            reason = (
                f"{rule.trigger_metric} worsened after adjustment: "
                f"before={trigger_before}, after={trigger_values_after}; "
                f"reverting {param} to default {reverted_value}"
            )

            db = await get_db()
            try:
                await db.execute(
                    "UPDATE ops_metric_adjustments SET reverted = 1, "
                    "reverted_at = ?, revert_reason = ? WHERE id = ?",
                    (now, reason, row["id"]),
                )
                await db.commit()
            finally:
                await db.close()

            logger.info("Auto-tuner revert: %s", reason)
            reverts += 1

    return reverts


async def run_auto_tuner(all_metrics: dict) -> int:
    """Evaluate all tuning rules and apply corrections. Returns count of adjustments."""
    # Flatten metrics from all tiers into one dict
    flat: dict = {}
    for tier_metrics in all_metrics.values():
        if isinstance(tier_metrics, dict):
            for k, v in tier_metrics.items():
                if isinstance(v, dict) and "p50" in v:
                    # Percentile metrics: expose p50, p95, p99 as separate keys
                    for pct in ["p50", "p95", "p99"]:
                        flat[f"{k}.{pct}"] = v[pct]
                else:
                    flat[k] = v

    adjustments = 0
    for rule in TUNING_RULES:
        try:
            if await evaluate_and_adjust(rule, flat):
                adjustments += 1
        except Exception:
            logger.exception("Auto-tuner error for rule %s", rule.parameter)

    # Revert check phase: detect worsening metrics and roll back bad adjustments
    rules_by_param = {r.parameter: r for r in TUNING_RULES}
    try:
        reverts = await _check_and_revert(rules_by_param)
        if reverts:
            logger.info("Auto-tuner reverted %d parameter(s)", reverts)
    except Exception:
        logger.exception("Auto-tuner error during revert check")

    return adjustments
