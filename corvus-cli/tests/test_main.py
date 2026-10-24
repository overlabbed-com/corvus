"""main.py - every command exercised through typer's CliRunner against a mocked HTTP layer."""

from __future__ import annotations

import runpy
import sys
import warnings

import pytest
from typer.testing import CliRunner

from corvus_cli.main import app

runner = CliRunner()


def run(*args: str):
    """Invoke the CLI and fail loudly on a non-zero exit."""
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"exit {result.exit_code}: {result.stdout} {result.stderr}"
    return result


# -- Pre-action checks --


def test_check_target_reports_recommendation_and_counts(api):
    api.on("GET", "/ops/events/targets/caddy/status", {
        "recommendation": "GO",
        "active_changes": [{}, {}],
        "recent_incidents": [{}],
    })
    out = run("check-target", "caddy").stdout
    assert "GO" in out
    assert "caddy" in out
    assert "Active changes: 2" in out
    assert "Recent incidents: 1" in out


def test_check_target_unknown_recommendation_has_no_count_lines(api):
    api.on("GET", "/ops/events/targets/caddy/status", {})
    out = run("check-target", "caddy").stdout
    assert "UNKNOWN" in out
    assert "Active changes" not in out
    assert "Recent incidents" not in out


def test_unrouted_request_exits_1_and_names_the_status(api):
    result = runner.invoke(app, ["metrics"])
    assert result.exit_code == 1
    assert "Error 404" in result.stdout


def test_server_error_body_is_printed_and_exits_1(api):
    api.on("GET", "/ops/events/context", {"detail": "boom"}, status=500)
    result = runner.invoke(app, ["context"])
    assert result.exit_code == 1
    assert "Error 500" in result.stdout
    assert "boom" in result.stdout


def test_blast_radius_with_no_dependencies(api):
    api.on("GET", "/ops/graph/blast-radius/redis", {"affected": []})
    out = run("blast-radius", "redis").stdout
    assert "redis" in out
    assert "No downstream dependencies found" in out


def test_blast_radius_renders_a_table_and_handles_missing_fields(api):
    api.on("GET", "/ops/graph/blast-radius/caddy", {
        "affected": [
            {"name": "redis", "host": "tmtdockp01", "depth": 2},
            {"name": "db"},
        ],
    })
    out = run("blast-radius", "caddy").stdout
    assert "Blast Radius: caddy" in out
    assert "redis" in out
    assert "tmtdockp01" in out
    assert "db" in out
    assert "?" in out


def test_dependency_chain_prints_the_payload(api):
    api.on("GET", "/ops/graph/dependency-chain/caddy", {"service": "caddy", "upstream": ["dns", "proxy"]})
    out = run("dependency-chain", "caddy").stdout
    assert "caddy" in out
    assert "upstream" in out
    assert "dns" in out


# -- Context --


def test_context_summarises_events_incidents_changes_and_gaps(api):
    api.on("GET", "/ops/events/context", {
        "events_24h": [{}, {}, {}],
        "active_incidents": [
            {"id": "INC-1", "target": "caddy", "severity": "critical", "title": "Down"},
        ],
        "active_changes": [{}],
        "gaps": {"total_open_gaps": 7},
    })
    out = run("context").stdout
    assert "Events (24h): 3" in out
    assert "Active incidents: 1" in out
    assert "Active changes: 1" in out
    assert "Open gaps: 7" in out
    assert "INC-1" in out
    assert "critical" in out


def test_context_with_no_incidents_skips_the_table(api):
    api.on("GET", "/ops/events/context", {"events_24h": [], "active_incidents": [], "active_changes": []})
    out = run("context").stdout
    assert "Open gaps: 0" in out
    assert "Active Incidents" not in out


# -- Changes --


def test_create_change_splits_comma_separated_targets(api):
    api.on("POST", "/ops/changes", {"id": "CHG-1"})
    out = run("create-change", "caddy, redis ,db", "-d", "drain the pool").stdout
    assert "Change created: CHG-1" in out
    body = api.call("POST", "/ops/changes").body
    assert body["targets"] == ["caddy", "redis", "db"]
    assert body["description"] == "drain the pool"
    assert body["created_by"] == "corvus-cli"
    assert body["rollback_plan"] == ""
    assert body["project"] == ""


def test_create_change_sends_the_optional_fields(api):
    api.on("POST", "/ops/changes", {"id": "CHG-2"})
    run(
        "create-change", "caddy", "-d", "drain",
        "--operator", "todd", "--rollback", "restart caddy", "--project", "ai",
    )
    body = api.call("POST", "/ops/changes").body
    assert body["created_by"] == "todd"
    assert body["rollback_plan"] == "restart caddy"
    assert body["project"] == "ai"


def test_close_change_defaults_to_completed(api):
    api.on("PATCH", "/ops/changes/CHG-1", {"id": "CHG-1"})
    out = run("close-change", "CHG-1").stdout
    assert "Change closed: CHG-1" in out
    assert api.call("PATCH", "/ops/changes/CHG-1").body == {"status": "completed", "outcome": "completed"}


def test_close_change_uses_the_given_outcome(api):
    api.on("PATCH", "/ops/changes/CHG-9", {"id": "CHG-9"})
    run("close-change", "CHG-9", "--outcome", "failed")
    assert api.call("PATCH", "/ops/changes/CHG-9").body["outcome"] == "failed"


def test_changes_with_none_active(api):
    api.on("GET", "/ops/changes/active", [])
    assert "No active changes" in run("changes").stdout


def test_changes_parses_targets_given_as_a_json_string(api):
    api.on("GET", "/ops/changes/active", [
        {"id": "CHG-1", "targets": '["caddy", "redis"]', "description": "drain", "created_by": "todd"},
        {"id": "CHG-2", "targets": ["db"], "description": "restart", "created_by": "bot"},
    ])
    out = run("changes").stdout
    assert "CHG-1" in out
    assert "caddy, redis" in out
    assert "CHG-2" in out
    assert "db" in out


# -- Events --


def test_emit_event_sends_the_payload(api):
    api.on("POST", "/ops/events", {"id": "EVT-1"})
    out = run(
        "emit-event", "-s", "agent", "-t", "change.started",
        "--target", "proxy", "--severity", "warning",
    ).stdout
    assert "Event emitted: EVT-1" in out
    assert api.call("POST", "/ops/events").body == {
        "source": "agent",
        "type": "change.started",
        "target": "proxy",
        "severity": "warning",
        "data": {},
    }


def test_emit_event_defaults_target_and_severity(api):
    api.on("POST", "/ops/events", {"id": "EVT-2"})
    run("emit-event", "--source", "agent", "--type", "session.started")
    body = api.call("POST", "/ops/events").body
    assert body["target"] == ""
    assert body["severity"] == "info"


# -- Incidents --


def test_incidents_with_none_found_sends_no_filters(api):
    api.on("GET", "/ops/incidents", [])
    assert "No incidents found" in run("incidents").stdout
    assert api.call("GET", "/ops/incidents").params == {}


def test_incidents_sends_every_filter_as_a_param(api):
    api.on("GET", "/ops/incidents", [])
    run("incidents", "--status", "open", "--target", "caddy", "--severity", "critical")
    assert api.call("GET", "/ops/incidents").params == {
        "status": "open",
        "target": "caddy",
        "severity": "critical",
    }


def test_incidents_renders_a_table(api):
    api.on("GET", "/ops/incidents", [
        {"id": "INC-1", "target": "caddy", "severity": "critical", "status": "open", "title": "Down"},
    ])
    out = run("incidents").stdout
    assert "Incidents" in out
    assert "INC-1" in out
    assert "caddy" in out
    assert "open" in out


def test_create_incident_sends_the_payload(api):
    api.on("POST", "/ops/incidents", {"id": "INC-2"})
    out = run(
        "create-incident", "caddy", "-t", "Down",
        "--description", "502s", "--severity", "critical", "--detected-by", "agent",
    ).stdout
    assert "Incident created: INC-2" in out
    assert api.call("POST", "/ops/incidents").body == {
        "target": "caddy",
        "title": "Down",
        "description": "502s",
        "severity": "critical",
        "detected_by": "agent",
    }


# -- CMDB --


def test_services_with_none_registered(api):
    api.on("GET", "/ops/cmdb", [])
    assert "No services found" in run("services").stdout
    assert api.call("GET", "/ops/cmdb").params == {}


def test_services_filters_and_marks_critical(api):
    api.on("GET", "/ops/cmdb", [
        {"name": "caddy", "service_type": "proxy", "host": "tmtdockp01", "critical": True},
        {"name": "db", "critical": False},
    ])
    out = run("services", "--service-type", "proxy", "--host", "tmtdockp01").stdout
    assert api.call("GET", "/ops/cmdb").params == {"service_type": "proxy", "host": "tmtdockp01"}
    assert "caddy" in out
    assert "🔴" in out
    assert "db" in out
    assert "-" in out


def test_service_prints_the_details(api):
    api.on("GET", "/ops/cmdb/caddy", {"name": "caddy", "critical": True, "host": "tmtdockp01"})
    out = run("service", "caddy").stdout
    assert "caddy" in out
    assert "critical" in out
    assert "tmtdockp01" in out


# -- Triage --


def test_triage_renders_the_full_diagnosis(api):
    api.on("POST", "/ops/runbooks/triage", {
        "status": "triaged",
        "triage_id": "TRG-1",
        "diagnosis": "port 443 closed",
        "confidence": 0.87,
        "escalation_required": True,
    })
    out = run("triage", "caddy", "--host", "tmtdockp01", "--service-type", "proxy").stdout
    assert "triaged — TRG-1" in out
    assert "Diagnosis: port 443 closed" in out
    assert "Confidence: 87%" in out
    assert "Escalation required" in out
    assert api.call("POST", "/ops/runbooks/triage").body == {
        "target": "caddy",
        "host": "tmtdockp01",
        "service_type": "proxy",
    }


def test_triage_minimal_response(api):
    api.on("POST", "/ops/runbooks/triage", {})
    out = run("triage", "caddy").stdout
    assert "unknown — ?" in out
    assert "Diagnosis" not in out
    assert "Escalation" not in out


# -- Metrics, gaps, signal quality --


def test_metrics_reports_every_field(api):
    api.on("GET", "/ops/metrics", {
        "events_24h": 42,
        "open_incidents": 2,
        "active_changes": 1,
        "false_positive_rate": 3.5,
        "compliance_rate": 91.2,
        "total_services": 12,
    })
    out = run("metrics").stdout
    assert "Events (24h): 42" in out
    assert "Open incidents: 2" in out
    assert "Active changes: 1" in out
    assert "FP rate: 3.5%" in out
    assert "Compliance rate: 91.2%" in out
    assert "Total services: 12" in out


def test_metrics_defaults_to_zero(api):
    api.on("GET", "/ops/metrics", {})
    out = run("metrics").stdout
    assert "Events (24h): 0" in out
    assert "FP rate: 0%" in out


def test_gaps_lists_the_workstream_breakdown(api):
    api.on("GET", "/ops/gaps", {"total_open_gaps": 5, "by_workstream": {"accuracy": 2, "coverage": 3}})
    out = run("gaps").stdout
    assert "Open gaps: 5" in out
    assert "accuracy: 2" in out
    assert "coverage: 3" in out


def test_gaps_without_a_workstream_breakdown(api):
    api.on("GET", "/ops/gaps", {"total_open_gaps": 0})
    out = run("gaps").stdout
    assert "Open gaps: 0" in out


def test_signal_quality_defaults_to_seven_days(api):
    api.on("GET", "/ops/signal-quality", {
        "total_resolved": 10,
        "false_positives": 1,
        "false_positive_rate": 10.0,
    })
    out = run("signal-quality").stdout
    assert "Total resolved (7d): 10" in out
    assert "False positives: 1" in out
    assert "FP rate: 10.0%" in out
    assert api.call("GET", "/ops/signal-quality").params == {"days": "7"}


def test_signal_quality_honours_a_custom_window(api):
    api.on("GET", "/ops/signal-quality", {"total_resolved": 4})
    out = run("signal-quality", "--days", "30").stdout
    assert "Total resolved (30d): 4" in out
    assert api.call("GET", "/ops/signal-quality").params == {"days": "30"}


# -- The HTTP client --


def test_bearer_token_is_sent_when_configured(api, monkeypatch):
    monkeypatch.setenv("CORVUS_TOKEN", "secret-token")
    api.on("GET", "/ops/metrics", {})
    run("metrics")
    assert api.call("GET", "/ops/metrics").headers.get("authorization") == "Bearer secret-token"


def test_no_authorization_header_without_a_token(api):
    api.on("GET", "/ops/metrics", {})
    run("metrics")
    assert "authorization" not in api.call("GET", "/ops/metrics").headers


def test_base_url_from_the_environment_reaches_the_request(api, monkeypatch):
    monkeypatch.setenv("CORVUS_URL", "http://corvus.test:9420/")
    api.on("GET", "/ops/events/context", {})
    run("context")
    assert api.call("GET", "/ops/events/context").url == "http://corvus.test:9420/ops/events/context"


# -- The entrypoint --


def test_help_lists_every_command():
    out = run("--help").stdout
    for name in (
        "check-target",
        "blast-radius",
        "dependency-chain",
        "context",
        "create-change",
        "close-change",
        "changes",
        "emit-event",
        "incidents",
        "create-incident",
        "services",
        "service",
        "triage",
        "metrics",
        "gaps",
        "signal-quality",
    ):
        assert name in out, f"{name} missing from --help"


def test_module_runs_as_main(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["corvus", "--help"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("corvus_cli.main", run_name="__main__")
    assert exc.value.code == 0
