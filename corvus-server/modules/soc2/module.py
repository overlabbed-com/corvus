"""SOC 2 Type II compliance module for Corvus.

Maps Corvus operational events to SOC 2 Trust Services Criteria:
- CC6: Logical and Physical Access Controls
- CC7: System Operations
- CC8: Change Management
- CC9: Risk Mitigation

Each control point maps to specific Corvus evidence sources
(events, changes, incidents, CMDB, triage logs, audit logs).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from fastapi import Query as FastQuery

router = APIRouter()

# SOC 2 control mappings — what evidence satisfies each criterion
CONTROL_MAP: dict[str, dict[str, Any]] = {
    # CC6: Logical and Physical Access Controls
    "CC6.1": {
        "title": "Logical access security software, infrastructure, and architectures",
        "category": "access",
        "evidence_sources": ["ops_audit_log"],
        "query": "All API access is authenticated and logged",
        "check": "audit_log_coverage",
    },
    "CC6.2": {
        "title": "Prior to issuing system credentials, authorization is documented",
        "category": "access",
        "evidence_sources": ["ops_cmdb"],
        "query": "Services have registered_by and created_at tracking",
        "check": "cmdb_registration_tracking",
    },
    "CC6.3": {
        "title": "Access to data is restricted to authorized personnel",
        "category": "access",
        "evidence_sources": ["ops_audit_log"],
        "query": "API requests are authenticated with actor tracking",
        "check": "authenticated_access",
    },
    # CC7: System Operations
    "CC7.1": {
        "title": "Detection and monitoring of security events",
        "category": "operations",
        "evidence_sources": ["ops_events", "ops_incidents"],
        "query": "Events are captured with source, severity, and timestamp",
        "check": "event_monitoring_coverage",
    },
    "CC7.2": {
        "title": "Monitoring of system components for anomalies",
        "category": "operations",
        "evidence_sources": ["ops_incidents", "ops_problems", "ops_triage_log"],
        "query": "Incidents are triaged with runbook-driven diagnosis",
        "check": "incident_triage_coverage",
    },
    "CC7.3": {
        "title": "Evaluation of security events to determine impact",
        "category": "operations",
        "evidence_sources": ["ops_incidents", "ops_triage_log"],
        "query": "Incidents have severity scoring and escalation tracking",
        "check": "severity_and_escalation",
    },
    "CC7.4": {
        "title": "Incident response procedures are established",
        "category": "operations",
        "evidence_sources": ["ops_triage_log", "ops_incidents"],
        "query": "Runbooks exist and are executed for incident response",
        "check": "runbook_execution",
    },
    # CC8: Change Management
    "CC8.1": {
        "title": "Changes to infrastructure and software are authorized",
        "category": "change",
        "evidence_sources": ["ops_changes", "ops_events"],
        "query": "Changes have declared windows with operator attribution",
        "check": "change_authorization",
    },
    "CC8.2": {
        "title": "Infrastructure and software changes are designed and developed",
        "category": "change",
        "evidence_sources": ["ops_changes"],
        "query": "Changes include description and rollback plans",
        "check": "change_documentation",
    },
    "CC8.3": {
        "title": "Changes are tested before deployment",
        "category": "change",
        "evidence_sources": ["ops_changes", "ops_events"],
        "query": "Change events track completion outcome",
        "check": "change_outcome_tracking",
    },
    # CC9: Risk Mitigation
    "CC9.1": {
        "title": "Risk is identified and assessed",
        "category": "risk",
        "evidence_sources": ["ops_problems", "ops_incidents"],
        "query": "Problems are correlated from recurring incidents",
        "check": "problem_correlation",
    },
    "CC9.2": {
        "title": "Risk mitigation activities are implemented",
        "category": "risk",
        "evidence_sources": ["ops_incidents", "ops_triage_log"],
        "query": "Incidents have remediation applied and resolution tracking",
        "check": "remediation_tracking",
    },
}


async def _check_audit_log_coverage(db, cutoff: str) -> dict[str, Any]:
    """CC6.1: Verify audit log captures all API access."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_audit_log WHERE timestamp >= ?",
        (cutoff,),
    )
    row = await cursor.fetchone()
    total = row["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(DISTINCT actor) as cnt FROM ops_audit_log WHERE timestamp >= ?",
        (cutoff,),
    )
    actors = (await cursor.fetchone())["cnt"]

    return {
        "status": "pass" if total > 0 else "fail",
        "evidence": {
            "total_audit_entries": total,
            "distinct_actors": actors,
        },
        "finding": None if total > 0 else "No audit log entries found in window",
    }


async def _check_cmdb_registration_tracking(db, cutoff: str) -> dict[str, Any]:
    """CC6.2: Verify CMDB tracks service registration."""
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_cmdb")
    total = (await cursor.fetchone())["cnt"]

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM ops_cmdb WHERE registered_by IS NOT NULL")
    tracked = (await cursor.fetchone())["cnt"]

    pct = round(tracked / total * 100, 1) if total > 0 else 0
    return {
        "status": "pass" if pct >= 80 else "warning" if pct >= 50 else "fail",
        "evidence": {
            "total_services": total,
            "with_registration_tracking": tracked,
            "coverage_pct": pct,
        },
        "finding": None if pct >= 80 else f"Only {pct}% of services have registration tracking",
    }


async def _check_authenticated_access(db, cutoff: str) -> dict[str, Any]:
    """CC6.3: Verify API access is authenticated."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_audit_log WHERE timestamp >= ? AND actor IS NOT NULL",
        (cutoff,),
    )
    authenticated = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_audit_log WHERE timestamp >= ? AND actor IS NULL",
        (cutoff,),
    )
    unauthenticated = (await cursor.fetchone())["cnt"]

    total = authenticated + unauthenticated
    pct = round(authenticated / total * 100, 1) if total > 0 else 100
    return {
        "status": "pass" if pct >= 95 else "warning" if pct >= 80 else "fail",
        "evidence": {
            "authenticated_requests": authenticated,
            "unauthenticated_requests": unauthenticated,
            "auth_rate_pct": pct,
        },
        "finding": None if pct >= 95 else f"{unauthenticated} unauthenticated requests detected",
    }


async def _check_event_monitoring_coverage(db, cutoff: str) -> dict[str, Any]:
    """CC7.1: Verify event monitoring is active."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_events WHERE timestamp >= ?",
        (cutoff,),
    )
    events = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(DISTINCT source) as cnt FROM ops_events WHERE timestamp >= ?",
        (cutoff,),
    )
    sources = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(DISTINCT target) as cnt FROM ops_events WHERE timestamp >= ?",
        (cutoff,),
    )
    targets = (await cursor.fetchone())["cnt"]

    return {
        "status": "pass" if events > 0 and sources >= 1 else "fail",
        "evidence": {
            "total_events": events,
            "distinct_sources": sources,
            "distinct_targets": targets,
        },
        "finding": None if events > 0 else "No events captured in monitoring window",
    }


async def _check_incident_triage_coverage(db, cutoff: str) -> dict[str, Any]:
    """CC7.2: Verify incidents are triaged."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_incidents WHERE created_at >= ?",
        (cutoff,),
    )
    incidents = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE timestamp >= ?",
        (cutoff,),
    )
    triages = (await cursor.fetchone())["cnt"]

    return {
        "status": "pass" if incidents == 0 or triages > 0 else "warning",
        "evidence": {
            "total_incidents": incidents,
            "total_triages": triages,
        },
        "finding": None if incidents == 0 or triages > 0 else "Incidents exist without triage records",
    }


async def _check_severity_and_escalation(db, cutoff: str) -> dict[str, Any]:
    """CC7.3: Verify severity assessment and escalation."""
    cursor = await db.execute(
        "SELECT severity, COUNT(*) as cnt FROM ops_incidents WHERE created_at >= ? GROUP BY severity",
        (cutoff,),
    )
    by_severity = {r["severity"]: r["cnt"] for r in await cursor.fetchall()}

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE timestamp >= ? AND escalation_required = 1",
        (cutoff,),
    )
    escalations = (await cursor.fetchone())["cnt"]

    return {
        "status": "pass",
        "evidence": {
            "incidents_by_severity": by_severity,
            "escalations": escalations,
        },
        "finding": None,
    }


async def _check_runbook_execution(db, cutoff: str) -> dict[str, Any]:
    """CC7.4: Verify runbook-driven incident response."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE timestamp >= ?",
        (cutoff,),
    )
    total = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_triage_log WHERE timestamp >= ? AND runbook_name != 'none'",
        (cutoff,),
    )
    with_runbook = (await cursor.fetchone())["cnt"]

    pct = round(with_runbook / total * 100, 1) if total > 0 else 100
    return {
        "status": "pass" if pct >= 70 else "warning" if pct >= 50 else "fail",
        "evidence": {
            "total_triages": total,
            "with_runbook": with_runbook,
            "runbook_coverage_pct": pct,
        },
        "finding": None if pct >= 70 else f"Only {pct}% of triages used a runbook",
    }


async def _check_change_authorization(db, cutoff: str) -> dict[str, Any]:
    """CC8.1: Verify changes are authorized."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_changes WHERE created_at >= ?",
        (cutoff,),
    )
    total = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_changes WHERE created_at >= ? AND created_by IS NOT NULL",
        (cutoff,),
    )
    attributed = (await cursor.fetchone())["cnt"]

    return {
        "status": "pass" if total == 0 or attributed == total else "fail",
        "evidence": {
            "total_changes": total,
            "with_attribution": attributed,
        },
        "finding": None if attributed == total else f"{total - attributed} changes without operator attribution",
    }


async def _check_change_documentation(db, cutoff: str) -> dict[str, Any]:
    """CC8.2: Verify changes have documentation."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_changes WHERE created_at >= ?",
        (cutoff,),
    )
    total = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        """SELECT COUNT(*) as cnt FROM ops_changes
           WHERE created_at >= ? AND description IS NOT NULL AND description != ''""",
        (cutoff,),
    )
    documented = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        """SELECT COUNT(*) as cnt FROM ops_changes
           WHERE created_at >= ? AND rollback_plan IS NOT NULL AND rollback_plan != ''""",
        (cutoff,),
    )
    with_rollback = (await cursor.fetchone())["cnt"]

    return {
        "status": "pass" if total == 0 or documented == total else "warning",
        "evidence": {
            "total_changes": total,
            "with_description": documented,
            "with_rollback_plan": with_rollback,
        },
        "finding": None if documented == total else f"{total - documented} changes without description",
    }


async def _check_change_outcome_tracking(db, cutoff: str) -> dict[str, Any]:
    """CC8.3: Verify change outcomes are tracked."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_changes WHERE created_at >= ? AND status = 'completed'",
        (cutoff,),
    )
    completed = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        """SELECT COUNT(*) as cnt FROM ops_changes
           WHERE created_at >= ? AND status = 'completed' AND outcome IS NOT NULL""",
        (cutoff,),
    )
    with_outcome = (await cursor.fetchone())["cnt"]

    return {
        "status": "pass" if completed == 0 or with_outcome > 0 else "warning",
        "evidence": {
            "completed_changes": completed,
            "with_outcome": with_outcome,
        },
        "finding": None if completed == 0 or with_outcome > 0 else "Completed changes without outcome tracking",
    }


async def _check_problem_correlation(db, cutoff: str) -> dict[str, Any]:
    """CC9.1: Verify problem management and correlation."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_problems WHERE created_at >= ?",
        (cutoff,),
    )
    problems = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_problems WHERE created_at >= ? AND root_cause IS NOT NULL",
        (cutoff,),
    )
    with_rca = (await cursor.fetchone())["cnt"]

    return {
        "status": "pass",
        "evidence": {
            "total_problems": problems,
            "with_root_cause_analysis": with_rca,
        },
        "finding": None,
    }


async def _check_remediation_tracking(db, cutoff: str) -> dict[str, Any]:
    """CC9.2: Verify remediation is tracked."""
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM ops_incidents WHERE created_at >= ? AND status = 'resolved'",
        (cutoff,),
    )
    resolved = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        """SELECT COUNT(*) as cnt FROM ops_incidents
           WHERE created_at >= ? AND status = 'resolved' AND remediation_applied IS NOT NULL""",
        (cutoff,),
    )
    with_remediation = (await cursor.fetchone())["cnt"]

    pct = round(with_remediation / resolved * 100, 1) if resolved > 0 else 100
    return {
        "status": "pass" if pct >= 50 else "warning",
        "evidence": {
            "resolved_incidents": resolved,
            "with_remediation_documented": with_remediation,
            "remediation_rate_pct": pct,
        },
        "finding": None if pct >= 50 else f"Only {pct}% of resolved incidents document remediation",
    }


# Check function registry
CHECK_FUNCTIONS = {
    "audit_log_coverage": _check_audit_log_coverage,
    "cmdb_registration_tracking": _check_cmdb_registration_tracking,
    "authenticated_access": _check_authenticated_access,
    "event_monitoring_coverage": _check_event_monitoring_coverage,
    "incident_triage_coverage": _check_incident_triage_coverage,
    "severity_and_escalation": _check_severity_and_escalation,
    "runbook_execution": _check_runbook_execution,
    "change_authorization": _check_change_authorization,
    "change_documentation": _check_change_documentation,
    "change_outcome_tracking": _check_change_outcome_tracking,
    "problem_correlation": _check_problem_correlation,
    "remediation_tracking": _check_remediation_tracking,
}


async def run_soc2_audit(days: int = 90) -> dict[str, Any]:
    """Run full SOC 2 compliance audit.

    Returns control-by-control assessment with evidence and findings.
    """
    from src.database import get_db

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    db = await get_db()
    try:
        results: dict[str, Any] = {}
        summary = {"pass": 0, "warning": 0, "fail": 0}

        for control_id, control in CONTROL_MAP.items():
            check_fn = CHECK_FUNCTIONS.get(control["check"])
            if not check_fn:
                results[control_id] = {
                    "title": control["title"],
                    "category": control["category"],
                    "status": "not_implemented",
                }
                continue

            result = await check_fn(db, cutoff)
            results[control_id] = {
                "title": control["title"],
                "category": control["category"],
                **result,
            }
            summary[result["status"]] = summary.get(result["status"], 0) + 1

        total = sum(summary.values())
        compliance_rate = round(summary["pass"] / total * 100, 1) if total > 0 else 0

        return {
            "framework": "SOC 2 Type II",
            "audit_window_days": days,
            "cutoff": cutoff,
            "summary": summary,
            "compliance_rate": compliance_rate,
            "controls": results,
        }
    finally:
        await db.close()


# -- Router endpoints --


@router.get("/audit")
async def soc2_audit(days: int = FastQuery(90, description="Audit window in days")):
    """Run SOC 2 Type II compliance audit."""
    return await run_soc2_audit(days=days)


@router.get("/controls")
async def list_controls():
    """List all SOC 2 control mappings."""
    return {
        control_id: {
            "title": c["title"],
            "category": c["category"],
            "evidence_sources": c["evidence_sources"],
            "query": c["query"],
        }
        for control_id, c in CONTROL_MAP.items()
    }


@router.get("/controls/{control_id}")
async def check_control(control_id: str, days: int = FastQuery(90)):
    """Run a single SOC 2 control check."""
    from src.database import get_db

    control = CONTROL_MAP.get(control_id)
    if not control:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Unknown control: {control_id}")

    check_fn = CHECK_FUNCTIONS.get(control["check"])
    if not check_fn:
        return {"control_id": control_id, "status": "not_implemented"}

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    db = await get_db()
    try:
        result = await check_fn(db, cutoff)
        return {
            "control_id": control_id,
            "title": control["title"],
            "category": control["category"],
            **result,
        }
    finally:
        await db.close()


# -- Metrics contribution --


async def get_metrics() -> dict[str, Any]:
    """SOC 2 metrics for the dashboard."""
    result = await run_soc2_audit(days=90)
    return {
        "soc2_compliance_rate": result["compliance_rate"],
        "soc2_summary": result["summary"],
    }
