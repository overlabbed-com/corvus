"""Tests for Corvus CLI."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.corvus_cli import app

runner = CliRunner()


def _mock_response(data, status_code=200, text=""):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = text or json.dumps(data)
    return resp


def _mock_client(response):
    """Create a mock httpx.Client context manager."""
    client = MagicMock()
    client.get.return_value = response
    client.post.return_value = response
    client.patch.return_value = response
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


class TestStatus:
    @patch("cli.corvus_cli._client")
    def test_status_go(self, mock_client_fn):
        client = _mock_client(_mock_response({"signal": "GO", "reasons": []}))
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["status", "caddy"])
        assert result.exit_code == 0
        assert "GO" in result.output

    @patch("cli.corvus_cli._client")
    def test_status_stop(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                {
                    "signal": "STOP",
                    "active_changes": [{"id": "CHG-1"}],
                    "open_incidents": [],
                    "reasons": ["Active change window"],
                }
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["status", "vllm"])
        assert result.exit_code == 0
        assert "STOP" in result.output
        assert "Active changes: 1" in result.output


class TestBlastRadius:
    @patch("cli.corvus_cli._client")
    def test_with_affected(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                {
                    "affected": [
                        {"name": "litellm", "depth": 1, "host": "dockp01"},
                        {"name": "openwebui", "depth": 2, "host": "dockp01"},
                    ]
                }
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["blast-radius", "caddy"])
        assert result.exit_code == 0
        assert "2 services affected" in result.output
        assert "litellm" in result.output

    @patch("cli.corvus_cli._client")
    def test_no_affected(self, mock_client_fn):
        client = _mock_client(_mock_response({"affected": []}))
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["blast-radius", "leaf-service"])
        assert result.exit_code == 0
        assert "No downstream" in result.output


class TestContext:
    @patch("cli.corvus_cli._client")
    def test_all_clear(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                {
                    "active_changes": [],
                    "open_incidents": [],
                    "recent_events": [],
                    "gap_summary": {"total_open_gaps": 0, "by_workstream": {}},
                }
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["context"])
        assert result.exit_code == 0
        assert "All clear" in result.output

    @patch("cli.corvus_cli._client")
    def test_with_incidents(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                {
                    "active_changes": [],
                    "open_incidents": [{"id": "INC-1", "title": "GPU OOM", "severity": "critical"}],
                    "recent_events": [],
                    "gap_summary": {"total_open_gaps": 0, "by_workstream": {}},
                }
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["context"])
        assert result.exit_code == 0
        assert "Open Incidents: 1" in result.output
        assert "GPU OOM" in result.output


class TestCollect:
    @patch("cli.corvus_cli._client")
    def test_collect_success(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                {
                    "status": "completed",
                    "hosts": 3,
                    "resolved": 15,
                    "edges": 10,
                }
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["collect"])
        assert result.exit_code == 0
        assert "complete" in result.output
        assert "Hosts: 3" in result.output

    @patch("cli.corvus_cli._client")
    def test_collect_skipped(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                {
                    "status": "skipped",
                    "message": "No Docker hosts configured",
                }
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["collect"])
        assert result.exit_code == 0
        assert "Skipped" in result.output


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


class TestIncidents:
    @patch("cli.corvus_cli._client")
    def test_list_empty(self, mock_client_fn):
        client = _mock_client(_mock_response([]))
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["incidents", "list"])
        assert result.exit_code == 0
        assert "No incidents" in result.output

    @patch("cli.corvus_cli._client")
    def test_list_with_incidents(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                [
                    {"id": "INC-1", "title": "GPU OOM", "severity": "critical", "target": "vllm", "status": "open"},
                ]
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["incidents", "list"])
        assert result.exit_code == 0
        assert "INC-1" in result.output
        assert "GPU OOM" in result.output

    @patch("cli.corvus_cli._client")
    def test_create(self, mock_client_fn):
        client = _mock_client(_mock_response({"id": "INC-99"}))
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["incidents", "create", "--target", "caddy", "--title", "502 errors"])
        assert result.exit_code == 0
        assert "Created: INC-99" in result.output


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


class TestChanges:
    @patch("cli.corvus_cli._client")
    def test_create(self, mock_client_fn):
        client = _mock_client(_mock_response({"id": "CHG-1", "expires_at": "2026-03-31T12:00:00"}))
        mock_client_fn.return_value = client
        result = runner.invoke(
            app,
            [
                "changes",
                "create",
                "--targets",
                "vllm,litellm",
                "--description",
                "Model swap",
            ],
        )
        assert result.exit_code == 0
        assert "Created: CHG-1" in result.output

    @patch("cli.corvus_cli._client")
    def test_close(self, mock_client_fn):
        client = _mock_client(_mock_response({"status": "completed"}))
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["changes", "close", "CHG-1"])
        assert result.exit_code == 0
        assert "Closed: CHG-1" in result.output


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestEvents:
    @patch("cli.corvus_cli._client")
    def test_emit(self, mock_client_fn):
        client = _mock_client(_mock_response({"id": "EVT-1"}))
        mock_client_fn.return_value = client
        result = runner.invoke(
            app,
            [
                "events",
                "emit",
                "--type",
                "change.completed",
                "--target",
                "vllm",
            ],
        )
        assert result.exit_code == 0
        assert "Emitted: EVT-1" in result.output

    @patch("cli.corvus_cli._client")
    def test_watch(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                [
                    {
                        "timestamp": "2026-03-31T10:00:00",
                        "type": "change.completed",
                        "target": "vllm",
                        "severity": "info",
                    },
                ]
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["events", "watch"])
        assert result.exit_code == 0
        assert "change.completed" in result.output


# ---------------------------------------------------------------------------
# CMDB
# ---------------------------------------------------------------------------


class TestCMDB:
    @patch("cli.corvus_cli._client")
    def test_list(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                [
                    {"name": "caddy", "service_type": "proxy", "host": "dockp01", "critical": True},
                    {"name": "vllm", "service_type": "inference", "host": "dockp01", "critical": False},
                ]
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["cmdb", "list"])
        assert result.exit_code == 0
        assert "2 services" in result.output
        assert "caddy" in result.output

    @patch("cli.corvus_cli._client")
    def test_get(self, mock_client_fn):
        client = _mock_client(_mock_response({"name": "caddy", "service_type": "proxy"}))
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["cmdb", "get", "caddy"])
        assert result.exit_code == 0
        assert "caddy" in result.output


# ---------------------------------------------------------------------------
# Trust
# ---------------------------------------------------------------------------


class TestTrust:
    @patch("cli.corvus_cli._client")
    def test_list(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                [
                    {
                        "action_type": "remediation.restart:inference",
                        "trust_tier": "SUPERVISED",
                        "total_count": 25,
                        "success_count": 24,
                        "failure_count": 1,
                    },
                ]
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["trust", "list"])
        assert result.exit_code == 0
        assert "SUPERVISED" in result.output
        assert "remediation.restart:inference" in result.output

    @patch("cli.corvus_cli._client")
    def test_list_empty(self, mock_client_fn):
        client = _mock_client(_mock_response([]))
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["trust", "list"])
        assert result.exit_code == 0
        assert "empty" in result.output


# ---------------------------------------------------------------------------
# Gaps
# ---------------------------------------------------------------------------


class TestGaps:
    @patch("cli.corvus_cli._client")
    def test_sweep_clean(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                {
                    "total_new_gaps": 0,
                    "unseen_services": 0,
                    "stale_findings": 0,
                }
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["gaps"])
        assert result.exit_code == 0
        assert "No new gaps" in result.output

    @patch("cli.corvus_cli._client")
    def test_sweep_with_gaps(self, mock_client_fn):
        client = _mock_client(
            _mock_response(
                {
                    "total_new_gaps": 3,
                    "unseen_services": 2,
                    "stale_findings": 1,
                }
            )
        )
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["gaps"])
        assert result.exit_code == 0
        assert "3 new gap(s)" in result.output


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    @patch("cli.corvus_cli._client")
    def test_api_error(self, mock_client_fn):
        client = _mock_client(_mock_response({}, status_code=401, text="Unauthorized"))
        mock_client_fn.return_value = client
        result = runner.invoke(app, ["status", "caddy"])
        assert result.exit_code == 1
        assert "Error 401" in result.output
