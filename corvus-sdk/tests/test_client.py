"""Tests for CorvusClient — all API operations."""

import httpx
import pytest
import respx

from corvus_sdk import CorvusClient, CorvusError

BASE = "http://corvus-test:8000"
TOKEN = "test-token"


@pytest.fixture
def client():
    """Create a CorvusClient for testing."""
    return CorvusClient(BASE, token=TOKEN)


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    async def test_context_manager(self, client):
        async with client as c:
            assert c._client is not None
        assert client._client is None

    async def test_property_raises_outside_context(self, client):
        with pytest.raises(RuntimeError, match="context manager"):
            _ = client.client

    async def test_auth_header_set(self, client):
        async with client as c:
            assert c.client.headers["Authorization"] == f"Bearer {TOKEN}"


# ---------------------------------------------------------------------------
# Pre-action conflict check
# ---------------------------------------------------------------------------


class TestCheckTarget:
    @respx.mock
    async def test_go(self, client):
        respx.get(f"{BASE}/ops/events/targets/caddy/status").mock(
            return_value=httpx.Response(200, json={"signal": "GO", "reasons": []})
        )
        async with client as c:
            result = await c.check_target("caddy")
        assert result["signal"] == "GO"

    @respx.mock
    async def test_stop(self, client):
        respx.get(f"{BASE}/ops/events/targets/vllm/status").mock(
            return_value=httpx.Response(200, json={
                "signal": "STOP",
                "reasons": ["Active incident"],
                "open_incidents": [{"id": "INC-1"}],
            })
        )
        async with client as c:
            result = await c.check_target("vllm")
        assert result["signal"] == "STOP"
        assert len(result["open_incidents"]) == 1


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


class TestChanges:
    @respx.mock
    async def test_create_change(self, client):
        respx.post(f"{BASE}/ops/changes").mock(
            return_value=httpx.Response(200, json={
                "id": "CHG-1",
                "created_at": "2026-03-31T10:00:00",
                "created_by": "corvus-sdk",
                "status": "active",
                "targets": '["caddy"]',
                "description": "Update Caddyfile",
                "expires_at": "2026-03-31T11:00:00",
            })
        )
        async with client as c:
            change = await c.create_change(["caddy"], "Update Caddyfile")
        assert change.id == "CHG-1"
        assert change.targets == ["caddy"]
        assert change.status == "active"

    @respx.mock
    async def test_close_change(self, client):
        respx.patch(f"{BASE}/ops/changes/CHG-1").mock(
            return_value=httpx.Response(200, json={"status": "completed"})
        )
        async with client as c:
            result = await c.close_change("CHG-1")
        assert result["status"] == "completed"

    @respx.mock
    async def test_active_changes(self, client):
        respx.get(f"{BASE}/ops/changes/active").mock(
            return_value=httpx.Response(200, json=[{"id": "CHG-1"}])
        )
        async with client as c:
            result = await c.active_changes()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestEvents:
    @respx.mock
    async def test_emit_event(self, client):
        respx.post(f"{BASE}/ops/events").mock(
            return_value=httpx.Response(200, json={
                "id": "EVT-1",
                "timestamp": "2026-03-31T10:00:00",
                "source": "corvus-sdk",
                "type": "change.completed",
                "target": "caddy",
                "severity": "info",
            })
        )
        async with client as c:
            event = await c.emit_event("corvus-sdk", "change.completed", target="caddy")
        assert event.id == "EVT-1"
        assert event.type == "change.completed"

    @respx.mock
    async def test_get_context(self, client):
        respx.get(f"{BASE}/ops/events/context").mock(
            return_value=httpx.Response(200, json={
                "active_changes": [],
                "open_incidents": [],
                "recent_events": [],
            })
        )
        async with client as c:
            ctx = await c.get_context()
        assert "active_changes" in ctx


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


class TestIncidents:
    @respx.mock
    async def test_create_incident(self, client):
        respx.post(f"{BASE}/ops/incidents").mock(
            return_value=httpx.Response(200, json={
                "id": "INC-1",
                "created_at": "2026-03-31T10:00:00",
                "detected_by": "corvus-sdk",
                "target": "vllm",
                "status": "open",
                "severity": "warning",
                "title": "GPU OOM",
            })
        )
        async with client as c:
            inc = await c.create_incident("vllm", "GPU OOM")
        assert inc.id == "INC-1"
        assert inc.target == "vllm"

    @respx.mock
    async def test_list_incidents(self, client):
        respx.get(f"{BASE}/ops/incidents").mock(
            return_value=httpx.Response(200, json=[
                {"id": "INC-1", "title": "Test", "status": "open"},
            ])
        )
        async with client as c:
            incs = await c.list_incidents(status="open")
        assert len(incs) == 1


# ---------------------------------------------------------------------------
# CMDB
# ---------------------------------------------------------------------------


class TestCMDB:
    @respx.mock
    async def test_get_service(self, client):
        respx.get(f"{BASE}/ops/cmdb/caddy").mock(
            return_value=httpx.Response(200, json={
                "id": "SVC-1",
                "name": "caddy",
                "host": "host-01",
                "service_type": "proxy",
                "critical": True,
                "dependencies": '["litellm"]',
                "alert_policy": "default",
            })
        )
        async with client as c:
            svc = await c.get_service("caddy")
        assert svc.name == "caddy"
        assert svc.critical is True
        assert svc.dependencies == ["litellm"]

    @respx.mock
    async def test_list_services(self, client):
        respx.get(f"{BASE}/ops/cmdb").mock(
            return_value=httpx.Response(200, json=[
                {"name": "caddy", "service_type": "proxy"},
            ])
        )
        async with client as c:
            svcs = await c.list_services(service_type="proxy")
        assert len(svcs) == 1


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


class TestTriage:
    @respx.mock
    async def test_sync_triage(self, client):
        respx.post(f"{BASE}/ops/runbooks/triage").mock(
            return_value=httpx.Response(200, json={
                "status": "triaged",
                "triage_id": "TRG-1",
                "target": "vllm",
                "service_type": "inference",
                "diagnosis": "gpu_oom",
                "root_cause": "VRAM exhaustion",
                "confidence": 0.9,
                "escalation_required": False,
                "restart_safe": True,
            })
        )
        async with client as c:
            result = await c.triage("vllm", service_type="inference")
        assert result.diagnosis == "gpu_oom"
        assert result.confidence == 0.9

    @respx.mock
    async def test_async_triage_flow(self, client):
        respx.post(f"{BASE}/ops/runbooks/steps/triage/async").mock(
            return_value=httpx.Response(200, json={
                "status": "pending_steps",
                "triage_id": "TRG-2",
                "target": "caddy",
                "service_type": "proxy",
                "pending_steps": [{"id": "STEP-1", "command": "docker logs caddy"}],
            })
        )
        async with client as c:
            result = await c.start_async_triage("caddy")
        assert result.status == "pending_steps"
        assert len(result.pending_steps) == 1


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------


class TestProblems:
    @respx.mock
    async def test_list_problems(self, client):
        respx.get(f"{BASE}/ops/problems").mock(
            return_value=httpx.Response(200, json=[
                {"id": "PRB-1", "title": "Recurring GPU OOM", "status": "identified"},
            ])
        )
        async with client as c:
            problems = await c.list_problems(status="identified")
        assert len(problems) == 1


# ---------------------------------------------------------------------------
# Trust ledger
# ---------------------------------------------------------------------------


class TestTrust:
    @respx.mock
    async def test_trust_ledger(self, client):
        respx.get(f"{BASE}/ops/trust").mock(
            return_value=httpx.Response(200, json=[
                {"action_type": "remediation.restart:inference", "trust_tier": "SUPERVISED",
                 "total_count": 25, "success_count": 24},
            ])
        )
        async with client as c:
            ledger = await c.trust_ledger()
        assert len(ledger) == 1
        assert ledger[0]["trust_tier"] == "SUPERVISED"

    @respx.mock
    async def test_trust_tier(self, client):
        respx.get(f"{BASE}/ops/trust/remediation.restart:inference").mock(
            return_value=httpx.Response(200, json={
                "action_type": "remediation.restart:inference",
                "trust_tier": "SUPERVISED",
            })
        )
        async with client as c:
            tier = await c.trust_tier("remediation.restart:inference")
        assert tier["trust_tier"] == "SUPERVISED"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    @respx.mock
    async def test_config_drift(self, client):
        respx.get(f"{BASE}/ops/discovery/drift").mock(
            return_value=httpx.Response(200, json={"drifts": []})
        )
        async with client as c:
            result = await c.config_drift()
        assert result["drifts"] == []

    @respx.mock
    async def test_collect_connections(self, client):
        respx.post(f"{BASE}/ops/discovery/collect").mock(
            return_value=httpx.Response(200, json={
                "status": "completed", "hosts": 3, "resolved": 15, "edges": 10,
            })
        )
        async with client as c:
            result = await c.collect_connections()
        assert result["status"] == "completed"
        assert result["edges"] == 10


# ---------------------------------------------------------------------------
# Graph queries
# ---------------------------------------------------------------------------


class TestGraph:
    @respx.mock
    async def test_blast_radius(self, client):
        respx.get(f"{BASE}/ops/graph/blast-radius/caddy").mock(
            return_value=httpx.Response(200, json={
                "affected": [{"name": "litellm", "depth": 1}],
            })
        )
        async with client as c:
            result = await c.blast_radius("caddy")
        assert len(result["affected"]) == 1

    @respx.mock
    async def test_dependency_chain(self, client):
        respx.get(f"{BASE}/ops/graph/dependency-chain/litellm").mock(
            return_value=httpx.Response(200, json={
                "chain": [{"name": "postgresql", "depth": 1}],
            })
        )
        async with client as c:
            result = await c.dependency_chain("litellm")
        assert len(result["chain"]) == 1

    @respx.mock
    async def test_graph_stats(self, client):
        respx.get(f"{BASE}/ops/graph/stats").mock(
            return_value=httpx.Response(200, json={"nodes": 157, "edges": 346})
        )
        async with client as c:
            stats = await c.graph_stats()
        assert stats["nodes"] == 157

    @respx.mock
    async def test_correlated_gpu(self, client):
        respx.get(f"{BASE}/ops/graph/correlated-gpu").mock(
            return_value=httpx.Response(200, json={
                "services": [{"name": "vllm-primary"}, {"name": "vllm-embed"}],
            })
        )
        async with client as c:
            result = await c.correlated_gpu("host-01", 0)
        assert len(result["services"]) == 2

    @respx.mock
    async def test_expiring_cis(self, client):
        respx.get(f"{BASE}/ops/graph/expiring-cis").mock(
            return_value=httpx.Response(200, json={"expiring": []})
        )
        async with client as c:
            result = await c.expiring_cis(days=30)
        assert result["expiring"] == []


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------


class TestKnowledge:
    @respx.mock
    async def test_search(self, client):
        respx.get(f"{BASE}/ops/knowledge/search").mock(
            return_value=httpx.Response(200, json=[
                {"text": "vLLM restart procedure", "score": 0.95},
            ])
        )
        async with client as c:
            results = await c.search_knowledge("vllm restart")
        assert len(results) == 1

    @respx.mock
    async def test_ingest(self, client):
        respx.post(f"{BASE}/ops/knowledge/ingest").mock(
            return_value=httpx.Response(200, json={"id": "KB-1", "status": "ingested"})
        )
        async with client as c:
            result = await c.ingest_knowledge("vLLM needs --tool-call-parser qwen3_coder")
        assert result["status"] == "ingested"


# ---------------------------------------------------------------------------
# Gaps
# ---------------------------------------------------------------------------


class TestGaps:
    @respx.mock
    async def test_gap_summary(self, client):
        respx.get(f"{BASE}/ops/gaps").mock(
            return_value=httpx.Response(200, json={
                "total_open_gaps": 3,
                "by_workstream": {"CI": 2, "NFI": 1},
            })
        )
        async with client as c:
            result = await c.gap_summary()
        assert result["total_open_gaps"] == 3

    @respx.mock
    async def test_gap_sweep(self, client):
        respx.post(f"{BASE}/ops/gaps/sweep").mock(
            return_value=httpx.Response(200, json={"total_new_gaps": 0})
        )
        async with client as c:
            result = await c.gap_sweep()
        assert result["total_new_gaps"] == 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    @respx.mock
    async def test_metrics(self, client):
        respx.get(f"{BASE}/ops/metrics").mock(
            return_value=httpx.Response(200, json={"total_events_24h": 42})
        )
        async with client as c:
            m = await c.metrics()
        assert m["total_events_24h"] == 42

    @respx.mock
    async def test_compliance_audit(self, client):
        respx.get(f"{BASE}/ops/metrics/compliance").mock(
            return_value=httpx.Response(200, json={"coverage_rate": 95.0})
        )
        async with client as c:
            result = await c.compliance_audit()
        assert result["coverage_rate"] == 95.0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    @respx.mock
    async def test_api_error_raises_corvus_error(self, client):
        respx.get(f"{BASE}/ops/events/targets/test/status").mock(
            return_value=httpx.Response(401, json={"detail": "Unauthorized"})
        )
        async with client as c:
            with pytest.raises(CorvusError) as exc_info:
                await c.check_target("test")
        assert exc_info.value.status_code == 401
        assert "Unauthorized" in str(exc_info.value)

    @respx.mock
    async def test_404_error(self, client):
        respx.get(f"{BASE}/ops/cmdb/nonexistent").mock(
            return_value=httpx.Response(404, text="Not found")
        )
        async with client as c:
            with pytest.raises(CorvusError) as exc_info:
                await c.get_service("nonexistent")
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_500_error(self, client):
        respx.get(f"{BASE}/ops/metrics").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with client as c:
            with pytest.raises(CorvusError):
                await c.metrics()
