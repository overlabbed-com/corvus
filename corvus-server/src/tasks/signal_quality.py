"""Signal quality — baseline-aware alerting and false positive reduction.

Provides:
- Baseline behavior checking: "certbot restarts daily = not incident"
- Intelligent severity scoring: service_type + critical + dependency_count
- False positive tracking and rate calculation
- Known-noisy service suppression

Addresses Phase 1d exit criterion: <20% false positive rate.
"""

import json
import logging
from typing import Any

from src.database import get_db

logger = logging.getLogger(__name__)

# Default baselines for common service types.
# These are overridden by CMDB per-service baseline_behavior.
DEFAULT_BASELINES: dict[str, dict[str, Any]] = {
    "utility": {
        "expected_restarts_per_day": 5,
        "expected_events": ["remediation.restart"],
        "noise_level": "high",
    },
    "proxy": {
        "expected_restarts_per_day": 0,
        "expected_events": [],
        "noise_level": "low",
    },
    "inference": {
        "expected_restarts_per_day": 0,
        "expected_events": [],
        "noise_level": "low",
    },
    "database": {
        "expected_restarts_per_day": 0,
        "expected_events": [],
        "noise_level": "low",
    },
    "secrets": {
        "expected_restarts_per_day": 0,
        "expected_events": [],
        "noise_level": "low",
    },
    "monitoring": {
        "expected_restarts_per_day": 1,
        "expected_events": [],
        "noise_level": "medium",
    },
    "automation": {
        "expected_restarts_per_day": 0,
        "expected_events": [],
        "noise_level": "low",
    },
    "media": {
        "expected_restarts_per_day": 1,
        "expected_events": ["remediation.restart"],
        "noise_level": "medium",
    },
}

# Severity weights for scoring
SEVERITY_WEIGHTS = {
    "critical": 4,
    "high": 3,
    "warning": 2,
    "medium": 1,
    "low": 0,
    "info": 0,
}


async def get_service_baseline(service_name: str) -> dict[str, Any]:
    """Get the effective baseline for a service.

    Priority: CMDB baseline_behavior > service_type default > global default.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT service_type, baseline_behavior, critical, alert_policy FROM ops_cmdb WHERE name = ?",
            (service_name,),
        )
        row = await cursor.fetchone()

        if not row:
            return {"source": "default", "expected_restarts_per_day": 1, "noise_level": "unknown"}

        # CMDB baseline overrides type defaults
        baseline = json.loads(row["baseline_behavior"]) if row["baseline_behavior"] != "{}" else {}
        if baseline:
            baseline["source"] = "cmdb"
            baseline["service_type"] = row["service_type"]
            baseline["critical"] = bool(row["critical"])
            baseline["alert_policy"] = row["alert_policy"]
            return baseline

        # Fall back to service_type default
        svc_type = row["service_type"] or ""
        type_baseline = DEFAULT_BASELINES.get(svc_type, {}).copy()
        if type_baseline:
            type_baseline["source"] = "service_type_default"
        else:
            type_baseline = {"source": "global_default", "expected_restarts_per_day": 1, "noise_level": "unknown"}

        type_baseline["service_type"] = row["service_type"]
        type_baseline["critical"] = bool(row["critical"])
        type_baseline["alert_policy"] = row["alert_policy"]
        return type_baseline
    finally:
        await db.close()


async def is_expected_behavior(service_name: str, event_type: str) -> dict[str, Any]:
    """Check if an event type is expected baseline behavior for a service.

    Returns:
        {"expected": True/False, "reason": str, "baseline": dict}
    """
    baseline = await get_service_baseline(service_name)
    expected_events = baseline.get("expected_events", [])
    alert_policy = baseline.get("alert_policy", "default")

    if alert_policy == "silent":
        return {"expected": True, "reason": f"Service {service_name} has alert_policy=silent", "baseline": baseline}

    if event_type in expected_events:
        return {"expected": True, "reason": f"{event_type} is expected for {service_name}", "baseline": baseline}

    return {"expected": False, "reason": f"{event_type} not in baseline for {service_name}", "baseline": baseline}


async def score_severity(
    target: str,
    base_severity: str,
) -> dict[str, Any]:
    """Intelligent severity scoring using service context.

    Factors:
    - Base severity from the event/incident
    - Service criticality (CMDB critical flag)
    - Service type (some types are inherently higher priority)
    - Dependency count (more dependents = higher impact)

    Returns: {"score": int, "effective_severity": str, "factors": dict}
    """
    base_score = SEVERITY_WEIGHTS.get(base_severity, 1)
    factors: dict[str, Any] = {"base_severity": base_severity, "base_score": base_score}

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT service_type, critical, dependencies FROM ops_cmdb WHERE name = ?",
            (target,),
        )
        row = await cursor.fetchone()

        bonus = 0

        if row:
            # Critical service bonus
            if row["critical"]:
                bonus += 1
                factors["critical_service"] = True

            # Dependency count bonus (services that others depend on)
            deps = json.loads(row["dependencies"]) if row["dependencies"] else []
            if len(deps) > 3:
                bonus += 1
                factors["high_dependency_count"] = len(deps)
        else:
            factors["not_in_cmdb"] = True

        final_score = min(base_score + bonus, 4)  # Cap at critical (4)

        # Map score back to severity
        score_to_severity = {0: "info", 1: "low", 2: "warning", 3: "high", 4: "critical"}
        effective = score_to_severity.get(final_score, base_severity)

        factors["bonus"] = bonus
        return {"score": final_score, "effective_severity": effective, "factors": factors}
    finally:
        await db.close()


async def get_false_positive_stats(days: int = 7) -> dict[str, Any]:
    """Calculate false positive rate over the given window.

    A false positive is an incident that was resolved with:
    - No remediation applied (was noise, not real issue)
    - Resolution time < 5 minutes (auto-closed or immediately dismissed)
    """
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    db = await get_db()
    try:
        # Total resolved incidents
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ops_incidents WHERE resolved_at >= ?",
            (cutoff,),
        )
        total_resolved = (await cursor.fetchone())["cnt"]

        if total_resolved == 0:
            return {
                "days": days,
                "total_resolved": 0,
                "false_positives": 0,
                "false_positive_rate": 0.0,
                "by_target": {},
            }

        # False positives: resolved with no remediation
        cursor = await db.execute(
            """SELECT COUNT(*) as cnt FROM ops_incidents
               WHERE resolved_at >= ? AND remediation_applied IS NULL""",
            (cutoff,),
        )
        no_remediation = (await cursor.fetchone())["cnt"]

        # Quick closes (< 5 min resolution)
        cursor = await db.execute(
            """SELECT COUNT(*) as cnt FROM ops_incidents
               WHERE resolved_at >= ?
               AND resolution_time_minutes IS NOT NULL
               AND resolution_time_minutes < 5
               AND remediation_applied IS NULL""",
            (cutoff,),
        )
        quick_closes = (await cursor.fetchone())["cnt"]

        # Per-target breakdown of false positives
        cursor = await db.execute(
            """SELECT target, COUNT(*) as cnt FROM ops_incidents
               WHERE resolved_at >= ? AND remediation_applied IS NULL
               GROUP BY target ORDER BY cnt DESC LIMIT 10""",
            (cutoff,),
        )
        by_target = {r["target"]: r["cnt"] for r in await cursor.fetchall()}

        fp_rate = round(no_remediation / total_resolved * 100, 1)

        return {
            "days": days,
            "total_resolved": total_resolved,
            "false_positives": no_remediation,
            "quick_closes": quick_closes,
            "false_positive_rate": fp_rate,
            "by_target": by_target,
        }
    finally:
        await db.close()


async def populate_default_baselines() -> dict[str, int]:
    """Populate baseline_behavior for services that have a service_type but no baseline.

    Uses DEFAULT_BASELINES for the service_type. Only updates services where
    baseline_behavior is empty ('{}').

    Returns: {"updated": count}
    """
    db = await get_db()
    try:
        updated = 0
        for svc_type, baseline in DEFAULT_BASELINES.items():
            cursor = await db.execute(
                """SELECT id FROM ops_cmdb
                   WHERE service_type = ? AND baseline_behavior = '{}'""",
                (svc_type,),
            )
            rows = await cursor.fetchall()
            for row in rows:
                await db.execute(
                    "UPDATE ops_cmdb SET baseline_behavior = ? WHERE id = ?",
                    (json.dumps(baseline), row["id"]),
                )
                updated += 1

        if updated:
            await db.commit()
            logger.info("Populated baselines for %d services", updated)

        return {"updated": updated}
    finally:
        await db.close()
