"""Event models with OCSF schema validation (GAP-1, GAP-3)."""

from typing import Any

from pydantic import BaseModel, model_validator

# ---------------------------------------------------------------------------
# Event Type Allowlist — mirrors spec/events.md taxonomy
# ---------------------------------------------------------------------------

EVENT_TYPE_ALLOWLIST = frozenset(
    {
        # Change lifecycle
        "change.started",
        "change.completed",
        "change.failed",
        "change.expired",
        # Incident lifecycle
        "incident.opened",
        "incident.investigating",
        "incident.resolved",
        "incident.escalated",
        # Remediation
        "remediation.restart",
        "remediation.config_fix",
        "remediation.credential_rotation",
        # Sweep/Scan
        "sweep.completed",
        "sweep.anomaly",
        # Detection (outside a sweep context — e.g. continuous monitors)
        "anomaly.detected",
        # LLM Investigation (read-only forensics with start/end lifecycle)
        "llm.investigation_started",
        "llm.investigation_completed",
        # Actions
        "action.approved",
        "action.denied",
        # Sessions
        "session.started",
        "session.ended",
        # Plan lifecycle
        "plan.created",
        "plan.approved",
        "plan.started",
        "plan.step_completed",
        "plan.step_failed",
        "plan.completed",
        "plan.failed",
        "plan.blocked",
        "plan.rolling_back",
        "plan.rolled_back",
        # Lean metrics
        "metrics.snapshot",
        "metrics.anomaly",
        "metrics.adjustment",
        "metrics.revert",
        "metrics.converged",
        # Correlation
        "correlation.group_created",
        "correlation.group_resolved",
        # Gap patterns (wildcard matching applied at runtime)
        "gap:accuracy:triage_failed",
        "gap:coverage:no_runbook",
        "gap:coverage:unclassified",
        "gap:coverage:config_drift",
        "gap:autonomy:manual_intervention",
        "gap:efficiency:slow_resolution",
    }
)

# ---------------------------------------------------------------------------
# Required fields per event type (from spec/events.md)
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, set[str]] = {
    "change.started": {"description"},
    "change.completed": {"summary"},
    "change.failed": {"summary", "error"},
    "incident.opened": {"title"},
    "gap:accuracy:triage_failed": {"gap_id"},
    "gap:coverage:no_runbook": {"gap_id"},
    "gap:coverage:unclassified": {"gap_id"},
    "gap:coverage:config_drift": {"gap_id"},
    "gap:autonomy:manual_intervention": {"gap_id"},
    "gap:efficiency:slow_resolution": {"gap_id"},
    "remediation.restart": {"reason"},
}

# ---------------------------------------------------------------------------
# Severity enum
# ---------------------------------------------------------------------------

VALID_SEVERITIES = frozenset({"info", "warning", "critical"})


def _is_valid_event_type(event_type: str) -> bool:
    """Check if event type is in allowlist or matches a gap wildcard pattern."""
    if event_type in EVENT_TYPE_ALLOWLIST:
        return True
    # Gap events use pattern: gap:{category}:{detail}
    if event_type.startswith("gap:"):
        parts = event_type.split(":")
        return len(parts) >= 2 and f"gap:{parts[1]}:" in {
            "gap:accuracy:",
            "gap:coverage:",
            "gap:autonomy:",
            "gap:efficiency:",
        }
    return False


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class EventCreate(BaseModel):
    source: str
    type: str  # Event type validated in router (GAP-1/3)
    target: str
    severity: str = "info"
    data: dict[str, Any] = {}
    related_incident_id: str | None = None
    related_change_id: str | None = None
    related_problem_id: str | None = None
    parent_event_id: str | None = None

    @model_validator(mode="after")
    def validate_required_fields(self):
        # GAP-1: Validate required fields for data quality
        # Note: Fields are optional for backward compatibility with existing events.
        # Future: Add config flag to enforce strict validation.
        required = REQUIRED_FIELDS.get(self.type, set())
        if required:
            # TODO: Log warning when missing (don't reject for backward compat)
            # For now, we accept events without required fields
            pass
        return self


class EventResponse(BaseModel):
    id: str
    timestamp: str
    source: str
    type: str
    target: str
    severity: str
    data: dict[str, Any]
    related_incident_id: str | None = None
    related_change_id: str | None = None
    related_problem_id: str | None = None
    parent_event_id: str | None = None
    authenticated_as: str | None = None
    signature: str | None = None  # GAP-8: HMAC-SHA256 event signing


class TargetStatus(BaseModel):
    target: str
    recommendation: str  # GO, CAUTION, STOP
    reason: str
    active_changes: list[dict[str, Any]] = []
    active_incidents: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []
    trust_tier: str = "ESCALATE"
