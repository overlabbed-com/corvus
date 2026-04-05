"""OCSF 1.3.0 event transformer.

Transforms internal SOP events to OCSF-compliant events for SIEM forwarding.
"""

from datetime import UTC, datetime
from typing import Any

# SOP event type → OCSF class mapping
OCSF_CLASS_MAP: dict[str, dict[str, Any]] = {
    "incident.opened": {
        "class_uid": 2005,
        "class_name": "Incident Finding",
        "category_uid": 2,
        "category_name": "Findings",
        "activity_id": 1,
        "activity_name": "Create",
    },
    "incident.investigating": {
        "class_uid": 2005,
        "class_name": "Incident Finding",
        "category_uid": 2,
        "category_name": "Findings",
        "activity_id": 2,
        "activity_name": "Update",
    },
    "incident.resolved": {
        "class_uid": 2005,
        "class_name": "Incident Finding",
        "category_uid": 2,
        "category_name": "Findings",
        "activity_id": 3,
        "activity_name": "Close",
    },
    "incident.escalated": {
        "class_uid": 2005,
        "class_name": "Incident Finding",
        "category_uid": 2,
        "category_name": "Findings",
        "activity_id": 99,
        "activity_name": "Other",
    },
    "change.started": {
        "class_uid": 5019,
        "class_name": "Device Config State Change",
        "category_uid": 5,
        "category_name": "Discovery",
        "activity_id": 1,
        "activity_name": "Execute",
    },
    "change.completed": {
        "class_uid": 5019,
        "class_name": "Device Config State Change",
        "category_uid": 5,
        "category_name": "Discovery",
        "activity_id": 2,
        "activity_name": "Complete",
    },
    "change.failed": {
        "class_uid": 5019,
        "class_name": "Device Config State Change",
        "category_uid": 5,
        "category_name": "Discovery",
        "activity_id": 3,
        "activity_name": "Fail",
    },
    "remediation.restart": {
        "class_uid": 7001,
        "class_name": "Remediation Activity",
        "category_uid": 7,
        "category_name": "Remediation",
        "activity_id": 1,
        "activity_name": "Execute",
    },
    "remediation.config_fix": {
        "class_uid": 7001,
        "class_name": "Remediation Activity",
        "category_uid": 7,
        "category_name": "Remediation",
        "activity_id": 1,
        "activity_name": "Execute",
    },
    "remediation.credential_rotation": {
        "class_uid": 7001,
        "class_name": "Remediation Activity",
        "category_uid": 7,
        "category_name": "Remediation",
        "activity_id": 1,
        "activity_name": "Execute",
    },
    "sweep.completed": {
        "class_uid": 6007,
        "class_name": "Scan Activity",
        "category_uid": 6,
        "category_name": "Application Activity",
        "activity_id": 2,
        "activity_name": "Complete",
    },
    "sweep.anomaly": {
        "class_uid": 2004,
        "class_name": "Detection Finding",
        "category_uid": 2,
        "category_name": "Findings",
        "activity_id": 1,
        "activity_name": "Create",
    },
    "action.approved": {
        "class_uid": 6003,
        "class_name": "API Activity",
        "category_uid": 6,
        "category_name": "Application Activity",
        "activity_id": 1,
        "activity_name": "Create",
    },
    "action.denied": {
        "class_uid": 6003,
        "class_name": "API Activity",
        "category_uid": 6,
        "category_name": "Application Activity",
        "activity_id": 3,
        "activity_name": "Fail",
    },
    "session.started": {
        "class_uid": 6002,
        "class_name": "Application Lifecycle",
        "category_uid": 6,
        "category_name": "Application Activity",
        "activity_id": 1,
        "activity_name": "Create",
    },
    "session.ended": {
        "class_uid": 6002,
        "class_name": "Application Lifecycle",
        "category_uid": 6,
        "category_name": "Application Activity",
        "activity_id": 3,
        "activity_name": "Close",
    },
}

SEVERITY_MAP = {
    "info": (1, "Informational"),
    "low": (2, "Low"),
    "warning": (3, "Medium"),
    "medium": (3, "Medium"),
    "high": (4, "High"),
    "critical": (5, "Critical"),
}


def transform_to_ocsf(event: dict[str, Any]) -> dict[str, Any]:
    """Transform an internal SOP event to an OCSF 1.3.0 event."""
    event_type = event.get("type", "")
    now = datetime.now(UTC).isoformat()

    # Determine OCSF class - check for gap events
    if event_type.startswith("gap:"):
        ocsf_class = {
            "class_uid": 2003,
            "class_name": "Compliance Finding",
            "category_uid": 2,
            "category_name": "Findings",
            "activity_id": 1,
            "activity_name": "Create",
        }
    else:
        ocsf_class = OCSF_CLASS_MAP.get(
            event_type,
            {
                "class_uid": 6003,
                "class_name": "API Activity",
                "category_uid": 6,
                "category_name": "Application Activity",
                "activity_id": 99,
                "activity_name": "Other",
            },
        )

    severity = event.get("severity", "info")
    sev_id, sev_name = SEVERITY_MAP.get(severity, (1, "Informational"))

    data = event.get("data", {})

    ocsf_event = {
        **ocsf_class,
        "severity_id": sev_id,
        "severity": sev_name,
        "time": event.get("timestamp", now),
        "message": data.get("summary", event.get("type", "")),
        "metadata": {
            "version": "1.3.0",
            "product": {
                "name": "Corvus",
                "vendor_name": "Corvus",
                "version": "1.0.0",
            },
            "logged_time": now,
        },
        "actor": {
            "agent": {
                "name": event.get("source", "unknown"),
                "type": "AI Ops Agent",
                "uid": f"{event.get('source', 'unknown')}:{event_type}",
            },
        },
        "resources": [
            {
                "uid": event.get("target", ""),
                "name": event.get("target", ""),
                "type": "service",
            },
        ],
        "observables": [
            {"name": "target", "type": "hostname", "value": event.get("target", "")},
        ],
        "unmapped": {
            "sop_event_type": event_type,
            "sop_event_id": event.get("id", ""),
            "related_incident_id": event.get("related_incident_id"),
            "related_change_id": event.get("related_change_id"),
            "related_problem_id": event.get("related_problem_id"),
            "parent_event_id": event.get("parent_event_id"),
        },
    }

    # Add finding_info for Finding class events
    if ocsf_class["category_uid"] == 2:
        ocsf_event["finding_info"] = {
            "uid": event.get("related_incident_id") or event.get("id", ""),
            "title": data.get("summary", event_type),
            "types": [event_type],
            "created_time": event.get("timestamp", now),
        }

    # Add evidence data if present
    if data:
        ocsf_event["evidences"] = [{"data": data}]

    return ocsf_event
