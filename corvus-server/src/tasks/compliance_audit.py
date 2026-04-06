"""Compliance audit — measures event emission coverage for agent actions.

Compares changes and incidents against emitted events to identify gaps
where agents took MODIFY+ actions without corresponding SOP event emissions.

Addresses Issue #3: >90% event coverage target.
"""

import json
from typing import Any

import aiosqlite


async def run_compliance_audit(
    db: aiosqlite.Connection,
    since: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Run a compliance audit across changes, incidents, and events.

    Args:
        db: An open aiosqlite connection (caller manages lifecycle).
        since: Optional ISO8601 timestamp — only audit items after this time.
        source: Optional agent name filter (e.g. 'my-agent', 'ops-bot').

    Returns a dict with:
    - changes: {total, covered, uncovered: [...]}
    - incidents: {total, covered, uncovered: [...]}
    - compliance_rate: percentage across both changes and incidents
    - by_source: per-source/agent compliance breakdown (changes + incidents)
    """
    result: dict[str, Any] = {}
    source_stats: dict[str, dict[str, int]] = {}

    # --- Bulk-fetch covered change IDs (eliminates N+1) ---
    evt_query = "SELECT DISTINCT related_change_id FROM ops_events WHERE related_change_id IS NOT NULL"
    evt_params: list[str] = []
    if since:
        evt_query += " AND timestamp >= ?"
        evt_params.append(since)
    cursor = await db.execute(evt_query, evt_params)
    covered_change_ids = {row["related_change_id"] for row in await cursor.fetchall()}

    # --- Change compliance ---
    chg_query = "SELECT id, created_by, targets, description FROM ops_changes WHERE 1=1"
    chg_params: list[str] = []
    if since:
        chg_query += " AND created_at >= ?"
        chg_params.append(since)
    if source:
        chg_query += " AND created_by = ?"
        chg_params.append(source)
    cursor = await db.execute(chg_query, chg_params)
    changes = await cursor.fetchall()

    compliant_changes = 0
    uncovered_changes: list[dict[str, Any]] = []

    for change in changes:
        chg_source = change["created_by"]
        if chg_source not in source_stats:
            source_stats[chg_source] = {"total": 0, "compliant": 0}
        source_stats[chg_source]["total"] += 1

        if change["id"] in covered_change_ids:
            compliant_changes += 1
            source_stats[chg_source]["compliant"] += 1
        else:
            targets = json.loads(change["targets"]) if isinstance(change["targets"], str) else change["targets"]
            uncovered_changes.append(
                {
                    "type": "change_without_event",
                    "id": change["id"],
                    "source": chg_source,
                    "targets": targets,
                    "description": change["description"],
                    "message": f"Change {change['id']} by {chg_source} has no corresponding events",
                }
            )

    total_changes = len(changes)
    result["changes"] = {
        "total": total_changes,
        "covered": compliant_changes,
        "uncovered": uncovered_changes,
    }

    # --- Bulk-fetch covered incident IDs (eliminates N+1) ---
    inc_evt_query = "SELECT DISTINCT related_incident_id FROM ops_events WHERE related_incident_id IS NOT NULL"
    inc_evt_params: list[str] = []
    if since:
        inc_evt_query += " AND timestamp >= ?"
        inc_evt_params.append(since)
    cursor = await db.execute(inc_evt_query, inc_evt_params)
    covered_incident_ids = {row["related_incident_id"] for row in await cursor.fetchall()}

    # --- Incident compliance ---
    inc_query = "SELECT id, detected_by, target, title FROM ops_incidents WHERE 1=1"
    inc_params: list[str] = []
    if since:
        inc_query += " AND created_at >= ?"
        inc_params.append(since)
    if source:
        inc_query += " AND detected_by = ?"
        inc_params.append(source)
    cursor = await db.execute(inc_query, inc_params)
    incidents = await cursor.fetchall()

    compliant_incidents = 0
    uncovered_incidents: list[dict[str, Any]] = []

    for incident in incidents:
        inc_source = incident["detected_by"]
        if inc_source not in source_stats:
            source_stats[inc_source] = {"total": 0, "compliant": 0}
        source_stats[inc_source]["total"] += 1

        if incident["id"] in covered_incident_ids:
            compliant_incidents += 1
            source_stats[inc_source]["compliant"] += 1
        else:
            uncovered_incidents.append(
                {
                    "type": "incident_without_event",
                    "id": incident["id"],
                    "source": inc_source,
                    "target": incident["target"],
                    "title": incident["title"],
                    "message": f"Incident {incident['id']} has no corresponding events",
                }
            )

    total_incidents = len(incidents)
    result["incidents"] = {
        "total": total_incidents,
        "covered": compliant_incidents,
        "uncovered": uncovered_incidents,
    }

    # --- Overall compliance rate (changes + incidents) ---
    total_items = total_changes + total_incidents
    compliant_items = compliant_changes + compliant_incidents
    result["compliance_rate"] = round(compliant_items / total_items * 100, 1) if total_items > 0 else 100.0

    # --- Per-source breakdown (includes both changes and incidents) ---
    by_source: dict[str, dict[str, Any]] = {}
    for source, stats in source_stats.items():
        by_source[source] = {
            "total": stats["total"],
            "compliant": stats["compliant"],
            "compliance_rate": (round(stats["compliant"] / stats["total"] * 100, 1) if stats["total"] > 0 else 100.0),
        }
    result["by_source"] = by_source

    return result
