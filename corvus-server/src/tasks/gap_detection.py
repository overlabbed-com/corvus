"""Automated gap detection — operationalized blind spot detection.

Detects gaps in operational coverage and creates problem records.
Addresses Phase 1e exit criteria.

Gap patterns:
- gap:accuracy:unclassifiable — incident resolved with no root cause
- gap:efficiency:slow-resolution — resolution time > 2x baseline
- gap:coverage:no-runbook — triage found no matching runbook
- gap:coverage:untyped-service — CMDB service has no service_type
- gap:coverage:generic-fallback — triage used generic runbook, not service-specific
- gap:autonomy:manual-resolution — incident resolved by human, not agent
- gap:accuracy:wrong-recommendation — applied fix differs from runbook suggestion
- gap:monitoring:unseen-service — CMDB service not seen in 7+ days
- gap:security:stale-finding — threat finding unaddressed for 30+ days
- gap:autonomy:stuck-escalation — trust tier stuck at ESCALATE for 30+ days
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from src.config import RuntimeConfig
from src.database import get_db
from src.tasks.task_metrics import track_task

logger = logging.getLogger(__name__)

# Story 2.7: Baselines are now configurable via CMDB
# Import from baseline_config module
from src.tasks.baseline_config import (
    DEFAULT_BASELINE,
    get_resolution_baseline,
)


async def check_incident_gaps(incident_id: str) -> list[str]:
    """Check a resolved incident for gaps. Returns list of created problem IDs."""
    db = await get_db()
    created_problems: list[str] = []
    try:
        cursor = await db.execute("SELECT * FROM ops_incidents WHERE id = ?", (incident_id,))
        incident = await cursor.fetchone()
        if not incident or incident["status"] != "resolved":
            return []

        now = datetime.now(UTC).isoformat()
        target = incident["target"]

        # Gap: no root cause identified
        if not incident["root_cause"]:
            pid = await _create_gap(
                db,
                now,
                title=f"Unclassifiable failure on {target}",
                pattern=f"gap:accuracy:unclassifiable:{target}",
                root_cause="Incident resolved without identifying root cause",
                recommended_fix="CI: Add diagnosis rules for this failure pattern",
                workstream="CI",
                incident_id=incident_id,
            )
            if pid:
                created_problems.append(pid)

        # Gap: slow resolution
        if incident["resolution_time_minutes"] is not None:
            # Look up service_type for baseline
            cursor = await db.execute("SELECT service_type FROM ops_cmdb WHERE name = ?", (target,))
            svc = await cursor.fetchone()
            service_type = svc["service_type"] if svc else None
            # Story 2.7: Get baseline from CMDB or use default
            baseline = await get_resolution_baseline(service_type)

            if incident["resolution_time_minutes"] > baseline * 2:
                pid = await _create_gap(
                    db,
                    now,
                    title=(
                        f"Slow resolution on {target}"
                        f" ({incident['resolution_time_minutes']}min"
                        f" vs {baseline}min baseline)"
                    ),
                    pattern=f"gap:efficiency:slow-resolution:{target}",
                    root_cause=(f"Resolution took {incident['resolution_time_minutes']}min, baseline is {baseline}min"),
                    recommended_fix="CI: Review triage steps and investigate bottleneck",
                    workstream="CI",
                    incident_id=incident_id,
                )
                if pid:
                    created_problems.append(pid)

        # Gap: no remediation applied (potential false positive or manual resolution)
        if not incident["remediation_applied"]:
            pid = await _create_gap(
                db,
                now,
                title=f"No automated remediation on {target}",
                pattern=f"gap:autonomy:manual-resolution:{target}",
                root_cause="Incident resolved without documented remediation",
                recommended_fix="CI: Automate remediation for this failure type",
                workstream="CI",
                incident_id=incident_id,
            )
            if pid:
                created_problems.append(pid)

        await db.commit()
        return created_problems
    finally:
        await db.close()


async def check_cmdb_gaps() -> list[str]:
    """Check CMDB for untyped services. Returns list of created problem IDs."""
    db = await get_db()
    created_problems: list[str] = []
    try:
        now = datetime.now(UTC).isoformat()
        cursor = await db.execute("SELECT name FROM ops_cmdb WHERE service_type IS NULL")
        untyped = await cursor.fetchall()

        for svc in untyped:
            # Check if gap already exists
            cursor = await db.execute(
                "SELECT id FROM ops_problems WHERE pattern = ? AND status != 'resolved'",
                (f"gap:coverage:untyped-service:{svc['name']}",),
            )
            existing = await cursor.fetchone()
            if existing:
                continue

            pid = await _create_gap(
                db,
                now,
                title=f"Untyped service: {svc['name']}",
                pattern=f"gap:coverage:untyped-service:{svc['name']}",
                root_cause="Service registered without service_type classification",
                recommended_fix="NFI: Classify service and assign appropriate runbook",
                workstream="NFI",
            )
            if pid:
                created_problems.append(pid)

        if created_problems:
            await db.commit()
        return created_problems
    finally:
        await db.close()


async def check_trust_gaps() -> list[str]:
    """Check for action types stuck at ESCALATE with no executions for 30d."""
    db = await get_db()
    created_problems: list[str] = []
    try:
        now = datetime.now(UTC)
        thirty_days_ago = (now - timedelta(days=30)).isoformat()

        # Find action types at ESCALATE that haven't been executed recently
        cursor = await db.execute(
            """SELECT action_type FROM ops_trust_ledger
               WHERE trust_tier = 'ESCALATE' AND total_count > 0"""
        )
        stuck = await cursor.fetchall()

        for row in stuck:
            action_type = row["action_type"]
            # Check if any recent triage for this action type
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE action_type = ? AND timestamp >= ?",
                (action_type, thirty_days_ago),
            )
            recent = await cursor.fetchone()
            if recent["cnt"] == 0:
                pid = await _create_gap(
                    db,
                    now.isoformat(),
                    title=f"Action type stuck at ESCALATE: {action_type}",
                    pattern=f"gap:autonomy:stuck-escalation:{action_type}",
                    root_cause=f"No executions in 30 days for {action_type}",
                    recommended_fix="CI: Review whether this action type is still relevant",
                    workstream="CI",
                )
                if pid:
                    created_problems.append(pid)

        if created_problems:
            await db.commit()
        return created_problems
    finally:
        await db.close()


async def check_unseen_services() -> list[str]:
    """Check for CMDB services not seen in 7+ days.

    A service with last_seen older than 7 days may have been decommissioned
    without updating the CMDB, or monitoring may have stopped.
    """
    db = await get_db()
    created_problems: list[str] = []
    try:
        now = datetime.now(UTC)
        seven_days_ago = (now - timedelta(days=7)).isoformat()

        cursor = await db.execute(
            """SELECT name, last_seen FROM ops_cmdb
               WHERE last_seen IS NOT NULL AND last_seen < ?""",
            (seven_days_ago,),
        )
        unseen = await cursor.fetchall()

        for svc in unseen:
            pid = await _create_gap(
                db,
                now.isoformat(),
                title=f"Service not seen in 7+ days: {svc['name']}",
                pattern=f"gap:monitoring:unseen-service:{svc['name']}",
                root_cause=f"Last seen: {svc['last_seen']}",
                recommended_fix="NFI: Verify service is still running or decommission from CMDB",
                workstream="NFI",
            )
            if pid:
                created_problems.append(pid)

        if created_problems:
            await db.commit()
        return created_problems
    finally:
        await db.close()


async def check_stale_findings() -> list[str]:
    """Check for threat/security findings unaddressed for 30+ days.

    Looks for problems with pattern starting with 'gap:security:' or severity
    'critical'/'high' that have been open for 30+ days.
    """
    db = await get_db()
    created_problems: list[str] = []
    try:
        now = datetime.now(UTC)
        thirty_days_ago = (now - timedelta(days=30)).isoformat()

        # Find old unresolved problems that are security-related
        cursor = await db.execute(
            """SELECT id, title, pattern, created_at FROM ops_problems
               WHERE status NOT IN ('resolved')
               AND (pattern LIKE 'gap:security:%' OR severity IN ('critical', 'high'))
               AND created_at < ?""",
            (thirty_days_ago,),
        )
        stale = await cursor.fetchall()

        for finding in stale:
            stale_pattern = f"gap:security:stale-finding:{finding['id']}"
            # Don't create a stale-finding gap for another stale-finding gap
            if finding["pattern"] and finding["pattern"].startswith("gap:security:stale-finding:"):
                continue

            pid = await _create_gap(
                db,
                now.isoformat(),
                title=f"Stale finding (30d+): {finding['title']}",
                pattern=stale_pattern,
                root_cause=f"Problem {finding['id']} created {finding['created_at']}, still unresolved",
                recommended_fix="CI: Prioritize resolution or document risk acceptance",
                workstream="CI",
            )
            if pid:
                created_problems.append(pid)

        if created_problems:
            await db.commit()
        return created_problems
    finally:
        await db.close()


async def check_triage_gaps(triage_id: str) -> list[str]:
    """Check a specific triage for gaps. Returns list of created problem IDs.

    Detects:
    - gap:coverage:generic-fallback — diagnosis is 'unknown' AND confidence < 0.5
    - gap:accuracy:wrong-recommendation — incident remediation doesn't match triage diagnosis
    """
    db = await get_db()
    created_problems: list[str] = []
    try:
        now = datetime.now(UTC).isoformat()
        cursor = await db.execute("SELECT * FROM ops_triage_log WHERE id = ?", (triage_id,))
        triage = await cursor.fetchone()
        if not triage:
            return []

        target = triage["target"]

        # Gap: generic fallback — diagnosis is unknown and confidence < 0.5
        is_unknown = (triage["diagnosis"] or "unknown") == "unknown"
        low_confidence = (triage["confidence"] or 0) < RuntimeConfig.get("triage.confidence_threshold")
        if is_unknown and low_confidence:
            pid = await _create_gap(
                db,
                now,
                title=f"Generic fallback used for {target}",
                pattern=f"gap:coverage:generic-fallback:{target}",
                root_cause=f"Triage {triage_id} used generic runbook (confidence={triage['confidence']})",
                recommended_fix=f"NFI: Create service-specific runbook for {triage['service_type']}",
                workstream="NFI",
            )
            if pid:
                created_problems.append(pid)

        # Gap: wrong recommendation — remediation doesn't match diagnosis
        if triage["related_incident_id"] and triage["diagnosis"]:
            cursor = await db.execute(
                "SELECT * FROM ops_incidents WHERE id = ?",
                (triage["related_incident_id"],),
            )
            incident = await cursor.fetchone()
            if (
                incident
                and incident["remediation_applied"]
                and triage["diagnosis"] not in incident["remediation_applied"]
            ):
                pid = await _create_gap(
                    db,
                    now,
                    title=f"Wrong recommendation on {target}",
                    pattern=f"gap:accuracy:wrong-recommendation:{target}",
                    root_cause=(
                        f"Triage diagnosed '{triage['diagnosis']}' but "
                        f"remediation was '{incident['remediation_applied']}'"
                    ),
                    recommended_fix="CI: Review diagnosis rules for this failure pattern",
                    workstream="CI",
                    incident_id=triage["related_incident_id"],
                )
                if pid:
                    created_problems.append(pid)

        if created_problems:
            await db.commit()
        return created_problems
    finally:
        await db.close()


async def check_generic_fallback_triages() -> list[str]:
    """Check for triages that used a generic/fallback runbook.

    A triage with runbook_name='generic' or confidence < 0.3 indicates
    the system used a fallback instead of a service-specific runbook.
    """
    db = await get_db()
    created_problems: list[str] = []
    try:
        now = datetime.now(UTC)
        seven_days_ago = (now - timedelta(days=7)).isoformat()

        cursor = await db.execute(
            """SELECT target, service_type, COUNT(*) as cnt FROM ops_triage_log
               WHERE timestamp >= ?
               AND (runbook_name = 'generic' OR confidence < 0.3)
               GROUP BY target, service_type""",
            (seven_days_ago,),
        )
        fallbacks = await cursor.fetchall()

        for row in fallbacks:
            pid = await _create_gap(
                db,
                now.isoformat(),
                title=f"Generic fallback used for {row['target']} ({row['cnt']}x in 7d)",
                pattern=f"gap:coverage:generic-fallback:{row['target']}",
                root_cause=f"No service-specific runbook for {row['service_type'] or 'unknown'} type",
                recommended_fix=f"NFI: Create runbook for service_type={row['service_type']}",
                workstream="NFI",
            )
            if pid:
                created_problems.append(pid)

        if created_problems:
            await db.commit()
        return created_problems
    finally:
        await db.close()


async def check_compliance_gaps() -> list[str]:
    """Check for changes and incidents with no corresponding events.

    Detects agents taking MODIFY+ actions without emitting SOP events.
    Creates gap:compliance:missing-event problem records.
    """
    db = await get_db()
    created_problems: list[str] = []
    try:
        now = datetime.now(UTC)
        seven_days_ago = (now - timedelta(days=7)).isoformat()

        # Changes without events
        cursor = await db.execute(
            """SELECT c.id, c.created_by, c.description
               FROM ops_changes c
               LEFT JOIN ops_events e ON e.related_change_id = c.id
               WHERE c.created_at >= ? AND e.id IS NULL""",
            (seven_days_ago,),
        )
        uncovered_changes = await cursor.fetchall()

        for change in uncovered_changes:
            pid = await _create_gap(
                db,
                now.isoformat(),
                title=f"Change {change['id']} has no SOP event",
                pattern=f"gap:compliance:missing-event:change:{change['id']}",
                root_cause=(
                    f"Agent '{change['created_by']}' created change "
                    f"'{change['description']}' without emitting a corresponding event"
                ),
                recommended_fix="CI: Ensure all MODIFY+ actions emit SOP events",
                workstream="CI",
            )
            if pid:
                created_problems.append(pid)

        # Incidents without events
        cursor = await db.execute(
            """SELECT i.id, i.detected_by, i.target, i.title
               FROM ops_incidents i
               LEFT JOIN ops_events e ON e.related_incident_id = i.id
               WHERE i.created_at >= ? AND e.id IS NULL""",
            (seven_days_ago,),
        )
        uncovered_incidents = await cursor.fetchall()

        for incident in uncovered_incidents:
            pid = await _create_gap(
                db,
                now.isoformat(),
                title=f"Incident {incident['id']} on {incident['target']} has no SOP event",
                pattern=f"gap:compliance:missing-event:incident:{incident['id']}",
                root_cause=(
                    f"Agent '{incident['detected_by']}' created incident "
                    f"'{incident['title']}' without emitting a corresponding event"
                ),
                recommended_fix="CI: Ensure all incident actions emit SOP events",
                workstream="CI",
            )
            if pid:
                created_problems.append(pid)

        if created_problems:
            await db.commit()
            logger.info("Compliance gap check found %d uncovered actions", len(created_problems))
        return created_problems
    finally:
        await db.close()


async def get_gap_summary() -> dict:
    """Get a summary of all open gaps by category and workstream.

    Used in session briefings to surface blind spots.
    """
    db = await get_db()
    try:
        # Counts by workstream
        cursor = await db.execute(
            """SELECT workstream, COUNT(*) as cnt FROM ops_problems
               WHERE pattern LIKE 'gap:%' AND status != 'resolved'
               GROUP BY workstream"""
        )
        by_workstream = {(r["workstream"] or "unrouted"): r["cnt"] for r in await cursor.fetchall()}

        # Counts by gap category
        cursor = await db.execute(
            """SELECT pattern FROM ops_problems
               WHERE pattern LIKE 'gap:%' AND status != 'resolved'"""
        )
        rows = await cursor.fetchall()
        by_category: dict[str, int] = {}
        for row in rows:
            # Extract category: gap:accuracy:... -> accuracy
            parts = row["pattern"].split(":")
            category = parts[1] if len(parts) >= 2 else "unknown"
            by_category[category] = by_category.get(category, 0) + 1

        # Most recent gaps (top 5)
        cursor = await db.execute(
            """SELECT id, title, pattern, workstream, created_at FROM ops_problems
               WHERE pattern LIKE 'gap:%' AND status != 'resolved'
               ORDER BY created_at DESC LIMIT 5"""
        )
        recent = [dict(r) for r in await cursor.fetchall()]

        total = sum(by_workstream.values())
        return {
            "total_open_gaps": total,
            "by_workstream": by_workstream,
            "by_category": by_category,
            "recent": recent,
        }
    finally:
        await db.close()


async def run_gap_sweep() -> dict:
    """Run all sweep-based gap checks. Returns counts of new gaps found."""
    results = {}

    cmdb_gaps = await check_cmdb_gaps()
    results["untyped_services"] = len(cmdb_gaps)

    trust_gaps = await check_trust_gaps()
    results["stuck_escalations"] = len(trust_gaps)

    unseen_gaps = await check_unseen_services()
    results["unseen_services"] = len(unseen_gaps)

    stale_gaps = await check_stale_findings()
    results["stale_findings"] = len(stale_gaps)

    fallback_gaps = await check_generic_fallback_triages()
    results["generic_fallbacks"] = len(fallback_gaps)

    compliance_gaps = await check_compliance_gaps()
    results["compliance_gaps"] = len(compliance_gaps)

    # Run trust promotion sweep (not a gap, but a periodic sweep task)
    from src.tasks.trust_ledger import run_promotion_sweep

    promotion_result = await run_promotion_sweep()
    results["trust_promotions"] = promotion_result.get("promoted", 0)

    total = sum(v for k, v in results.items() if k != "trust_promotions")
    results["total_new_gaps"] = total

    if total:
        logger.info("Gap sweep found %d new gaps: %s", total, results)

    return results


async def run_gap_sweep_loop(interval_seconds: int = 3600):
    """Run gap sweep every hour (default)."""
    while True:
        try:
            with track_task("gap_sweep") as ctx:
                result = await run_gap_sweep()
                ctx["count"] = sum(result.values()) if result else 0
        except Exception:
            logger.exception("Error in gap sweep task")
        await asyncio.sleep(interval_seconds)


async def _create_gap(
    db,
    now: str,
    title: str,
    pattern: str,
    root_cause: str,
    recommended_fix: str,
    workstream: str,
    incident_id: str | None = None,
) -> str | None:
    """Create a gap problem record, deduplicating by pattern.

    If a gap with the same pattern exists and is unresolved, appends the
    incident to correlated_incidents instead of creating a duplicate.
    """
    # Check for existing unresolved gap
    cursor = await db.execute(
        "SELECT id, correlated_incidents FROM ops_problems WHERE pattern = ? AND status != 'resolved'",
        (pattern,),
    )
    existing = await cursor.fetchone()

    if existing:
        if incident_id:
            incidents = json.loads(existing["correlated_incidents"])
            if incident_id not in incidents:
                incidents.append(incident_id)
                await db.execute(
                    "UPDATE ops_problems SET correlated_incidents = ? WHERE id = ?",
                    (json.dumps(incidents), existing["id"]),
                )
        return None  # Not a new problem

    problem_id = f"PRB-{uuid.uuid4().hex[:8].upper()}"
    correlated = json.dumps([incident_id] if incident_id else [])

    await db.execute(
        """INSERT INTO ops_problems
           (id, created_at, status, title, pattern, root_cause,
            recommended_fix, severity, workstream, correlated_incidents)
           VALUES (?, ?, 'identified', ?, ?, ?, ?, 'medium', ?, ?)""",
        (problem_id, now, title, pattern, root_cause, recommended_fix, workstream, correlated),
    )
    return problem_id
