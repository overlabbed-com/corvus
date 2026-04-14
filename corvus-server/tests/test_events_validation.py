"""Tests for event type allowlist and OCSF schema validation (GAP-1, GAP-3).

Note: Required fields are warnings for backward compatibility, not errors.
"""

import pytest

# ---------------------------------------------------------------------------
# Event Type Allowlist Tests
# ---------------------------------------------------------------------------


class TestEventTypeAllowlist:
    """GAP-3: Unknown event types must be rejected with 400."""

    @pytest.mark.asyncio
    async def test_valid_change_started_is_accepted(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "change.started",
                "target": "test-service",
                "severity": "info",
                "data": {"description": "testing"},
            },
        )
        assert r.status_code == 201, r.json()

    @pytest.mark.asyncio
    async def test_valid_incident_opened_is_accepted(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "incident.opened",
                "target": "test-service",
                "severity": "warning",
                "data": {"title": "test incident", "description": "test"},
            },
        )
        assert r.status_code == 201, r.json()

    @pytest.mark.asyncio
    async def test_valid_remediation_restart_is_accepted(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "remediation.restart",
                "target": "test-service",
                "severity": "warning",
                "data": {"reason": "test"},
            },
        )
        assert r.status_code == 201, r.json()

    @pytest.mark.asyncio
    async def test_valid_session_started_is_accepted(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "session.started",
                "target": "",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 201, r.json()

    @pytest.mark.asyncio
    async def test_valid_gap_event_is_accepted(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "gap:accuracy:triage_failed",
                "target": "test-service",
                "severity": "warning",
                "data": {"gap_id": "test-gap", "service_type": "utility"},
            },
        )
        assert r.status_code == 201, r.json()

    @pytest.mark.asyncio
    async def test_valid_plan_events_are_accepted(self, client):
        for plan_type in (
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
        ):
            r = await client.post(
                "/ops/events",
                json={
                    "source": "test-agent",
                    "type": plan_type,
                    "target": "test-service",
                    "severity": "info",
                    "data": {},
                },
            )
            assert r.status_code == 201, f"Failed for {plan_type}: {r.json()}"

    @pytest.mark.asyncio
    async def test_valid_metrics_events_are_accepted(self, client):
        for metric_type in (
            "metrics.snapshot",
            "metrics.anomaly",
            "metrics.adjustment",
            "metrics.revert",
            "metrics.converged",
        ):
            r = await client.post(
                "/ops/events",
                json={
                    "source": "test-agent",
                    "type": metric_type,
                    "target": "test-service",
                    "severity": "info",
                    "data": {},
                },
            )
            assert r.status_code == 201, f"Failed for {metric_type}: {r.json()}"

    @pytest.mark.asyncio
    async def test_valid_correlation_events_are_accepted(self, client):
        for corr_type in ("correlation.group_created", "correlation.group_resolved"):
            r = await client.post(
                "/ops/events",
                json={
                    "source": "test-agent",
                    "type": corr_type,
                    "target": "test-service",
                    "severity": "warning",
                    "data": {},
                },
            )
            assert r.status_code == 201, f"Failed for {corr_type}: {r.json()}"

    @pytest.mark.asyncio
    async def test_unknown_event_type_is_rejected(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "completely.invalid.event.type",
                "target": "test-service",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.json()}"

    @pytest.mark.asyncio
    async def test_unknown_event_type_returns_valid_types(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "made.up.event",
                "target": "test-service",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 400
        body = r.json()
        assert "valid_types" in body["detail"] or "valid event type" in body["detail"].lower()

    @pytest.mark.asyncio
    async def test_typo_event_type_is_rejected(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "incident.resolvedd",  # typo — extra d
                "target": "test-service",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_case_mismatch_is_rejected(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "Incident.Opened",  # wrong case
                "target": "test-service",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Severity Validation Tests
# ---------------------------------------------------------------------------


class TestSeverityValidation:
    """Severity must be one of: info, warning, critical."""

    @pytest.mark.asyncio
    async def test_valid_severity_info_is_accepted(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "change.started",
                "target": "test-service",
                "severity": "info",
                "data": {"description": "test"},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_valid_severity_warning_is_accepted(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "change.started",
                "target": "test-service",
                "severity": "warning",
                "data": {"description": "test"},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_valid_severity_critical_is_accepted(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "change.started",
                "target": "test-service",
                "severity": "critical",
                "data": {"description": "test"},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_invalid_severity_is_rejected(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "change.started",
                "target": "test-service",
                "severity": "high",  # invalid — should be critical
                "data": {"description": "test"},
            },
        )
        assert r.status_code == 400, r.json()


# ---------------------------------------------------------------------------
# Backward Compatibility Tests
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Existing valid events must continue to work."""

    @pytest.mark.asyncio
    async def test_minimal_event_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "session.started",
                "target": "",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_sweep_completed_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "sweep.completed",
                "target": "fleet",
                "severity": "info",
                "data": {"services_checked": 42, "unhealthy": 1},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_action_approved_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "action.approved",
                "target": "test-service",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_action_denied_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "action.denied",
                "target": "test-service",
                "severity": "warning",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_change_completed_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "change.completed",
                "target": "test-service",
                "severity": "info",
                "data": {"summary": "Deploy successful"},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_incident_resolved_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "incident.resolved",
                "target": "test-service",
                "severity": "info",
                "data": {"resolution_summary": "Restarted service"},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_incident_investigating_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "incident.investigating",
                "target": "test-service",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_incident_escalated_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "incident.escalated",
                "target": "test-service",
                "severity": "warning",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_remediation_config_fix_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "remediation.config_fix",
                "target": "test-service",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_remediation_credential_rotation_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "remediation.credential_rotation",
                "target": "test-service",
                "severity": "warning",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_sweep_anomaly_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "sweep.anomaly",
                "target": "test-service",
                "severity": "warning",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_change_expired_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "change.expired",
                "target": "test-service",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_session_ended_still_works(self, client):
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "session.ended",
                "target": "",
                "severity": "info",
                "data": {},
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_change_started_without_description_still_works(self, client):
        """Required fields are warnings, not errors (backward compat)."""
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "change.started",
                "target": "test-service",
                "severity": "info",
                "data": {},  # missing description
            },
        )
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_incident_opened_without_title_still_works(self, client):
        """Required fields are warnings, not errors (backward compat)."""
        r = await client.post(
            "/ops/events",
            json={
                "source": "test-agent",
                "type": "incident.opened",
                "target": "test-service",
                "severity": "warning",
                "data": {"description": "test"},  # missing title
            },
        )
        assert r.status_code == 201
