"""Async HTTP client for the Corvus API.

Usage:
    async with CorvusClient("http://corvus:8000", token="my-token") as client:
        status = await client.check_target("caddy")
        if status["recommendation"] == "GO":
            change = await client.create_change(
                targets=["caddy"],
                description="Updating Caddyfile",
            )
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from corvus_sdk.models import (
    Change,
    Event,
    Incident,
    Service,
    StepResult,
    TriageResult,
)


class CorvusError(Exception):
    """Raised when the Corvus API returns an error."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Corvus API error {status_code}: {detail}")


class CorvusClient:
    """Async client for the Corvus operational governance API.

    Args:
        base_url: Corvus server URL (e.g. "http://corvus:8000")
        token: API bearer token
        timeout: Request timeout in seconds (default 30)
    """

    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> CorvusClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use 'async with CorvusClient(...) as client:' context manager")
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an API request and return JSON response."""
        resp = await self.client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                pass
            raise CorvusError(resp.status_code, detail)
        return resp.json()

    # -- Pre-action conflict check --

    async def check_target(self, target: str) -> dict[str, Any]:
        """Check target for conflicts before modifying.

        Returns dict with 'recommendation' (GO/CAUTION/STOP).
        """
        return await self._request("GET", f"/ops/events/targets/{target}/status")

    # -- Changes --

    async def create_change(
        self,
        targets: list[str],
        description: str,
        *,
        operator: str = "corvus-sdk",
        rollback_plan: str = "",
        project: str = "",
    ) -> Change:
        """Declare a change window."""
        data = await self._request(
            "POST",
            "/ops/changes",
            json={
                "targets": targets,
                "description": description,
                "created_by": operator,
                "rollback_plan": rollback_plan,
                "project": project,
            },
        )
        return Change(
            id=data["id"],
            created_at=data["created_at"],
            created_by=data["created_by"],
            status=data["status"],
            targets=json.loads(data["targets"]) if isinstance(data["targets"], str) else data["targets"],
            description=data["description"],
            rollback_plan=data.get("rollback_plan", ""),
            project=data.get("project", ""),
            expires_at=data.get("expires_at"),
        )

    async def close_change(self, change_id: str, outcome: str = "completed") -> dict[str, Any]:
        """Close a change window."""
        return await self._request(
            "PATCH",
            f"/ops/changes/{change_id}",
            json={"status": "completed", "outcome": outcome},
        )

    async def active_changes(self) -> list[dict[str, Any]]:
        """List active change windows."""
        return await self._request("GET", "/ops/changes/active")

    # -- Events --

    async def emit_event(
        self,
        source: str,
        event_type: str,
        *,
        target: str = "",
        severity: str = "info",
        data: dict[str, Any] | None = None,
    ) -> Event:
        """Emit an operational event."""
        resp = await self._request(
            "POST",
            "/ops/events",
            json={
                "source": source,
                "type": event_type,
                "target": target,
                "severity": severity,
                "data": data or {},
            },
        )
        return Event(
            id=resp["id"],
            timestamp=resp["timestamp"],
            source=resp["source"],
            type=resp["type"],
            target=resp["target"],
            severity=resp.get("severity", "info"),
        )

    async def get_context(self) -> dict[str, Any]:
        """Get 24h session briefing."""
        return await self._request("GET", "/ops/events/context")

    # -- Incidents --

    async def create_incident(
        self,
        target: str,
        title: str,
        *,
        description: str = "",
        severity: str = "warning",
        detected_by: str = "corvus-sdk",
    ) -> Incident:
        """Create an incident record."""
        data = await self._request(
            "POST",
            "/ops/incidents",
            json={
                "target": target,
                "title": title,
                "description": description,
                "severity": severity,
                "detected_by": detected_by,
            },
        )
        return Incident(
            id=data["id"],
            created_at=data["created_at"],
            detected_by=data["detected_by"],
            target=data["target"],
            status=data["status"],
            severity=data["severity"],
            title=data["title"],
            description=data.get("description"),
        )

    async def list_incidents(
        self,
        *,
        status: str | None = None,
        target: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        """List incidents with optional filters."""
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if target:
            params["target"] = target
        if severity:
            params["severity"] = severity
        return await self._request("GET", "/ops/incidents", params=params)

    # -- CMDB --

    async def get_service(self, name: str) -> Service:
        """Get service metadata from CMDB."""
        data = await self._request("GET", f"/ops/cmdb/{name}")
        return Service(
            id=data["id"],
            name=data["name"],
            host=data.get("host"),
            service_type=data.get("service_type"),
            critical=bool(data.get("critical")),
            dependencies=(
                json.loads(data["dependencies"])
                if isinstance(data.get("dependencies"), str)
                else data.get("dependencies", [])
            ),
            alert_policy=data.get("alert_policy", "default"),
        )

    async def list_services(
        self,
        *,
        service_type: str | None = None,
        host: str | None = None,
        critical: bool | None = None,
    ) -> list[dict[str, Any]]:
        """List CMDB services."""
        params: dict[str, str] = {}
        if service_type:
            params["service_type"] = service_type
        if host:
            params["host"] = host
        if critical is not None:
            params["critical"] = str(critical).lower()
        return await self._request("GET", "/ops/cmdb", params=params)

    # -- Triage (sync) --

    async def triage(
        self,
        target: str,
        *,
        host: str = "",
        service_type: str | None = None,
        investigation_data: dict[str, Any] | None = None,
    ) -> TriageResult:
        """Run synchronous triage with pre-collected investigation data."""
        data = await self._request(
            "POST",
            "/ops/runbooks/triage",
            json={
                "target": target,
                "host": host,
                "service_type": service_type,
                "investigation_data": investigation_data,
            },
        )
        return TriageResult(
            status=data.get("status", "triaged"),
            triage_id=data["triage_id"],
            target=data["target"],
            service_type=data["service_type"],
            runbook_name=data.get("runbook_name"),
            diagnosis=data.get("diagnosis"),
            root_cause=data.get("root_cause"),
            confidence=data.get("confidence", 0.0),
            escalation_required=data.get("escalation_required", False),
            restart_safe=data.get("restart_safe"),
        )

    # -- Triage (async — agent-driven) --

    async def start_async_triage(
        self,
        target: str,
        *,
        host: str = "",
        service_type: str | None = None,
    ) -> TriageResult:
        """Start async triage — returns pending steps for execution."""
        data = await self._request(
            "POST",
            "/ops/runbooks/steps/triage/async",
            json={
                "target": target,
                "host": host,
                "service_type": service_type,
            },
        )
        return TriageResult(
            status=data["status"],
            triage_id=data["triage_id"],
            target=data["target"],
            service_type=data["service_type"],
            runbook_name=data.get("runbook_name"),
            pending_steps=data.get("pending_steps", []),
        )

    async def submit_step(
        self,
        step_id: str,
        *,
        output: Any = None,
        error: str | None = None,
        success: bool = True,
    ) -> StepResult:
        """Submit the result of executing a runbook step."""
        data = await self._request(
            "POST",
            f"/ops/runbooks/steps/{step_id}/result",
            json={"output": output, "error": error, "success": success},
        )
        return StepResult(
            step_id=data["step_id"],
            status=data["status"],
            triage_id=data["triage_id"],
            all_steps_complete=data["all_steps_complete"],
            total_steps=data["total_steps"],
            pending_steps=data["pending_steps"],
        )

    async def continue_triage(self, triage_id: str) -> TriageResult:
        """Continue triage after all steps are submitted."""
        data = await self._request(
            "POST",
            f"/ops/runbooks/steps/triage/{triage_id}/continue",
        )
        return TriageResult(
            status=data.get("status", "triaged"),
            triage_id=data.get("triage_id", triage_id),
            target=data.get("target", ""),
            service_type=data.get("service_type", ""),
            runbook_name=data.get("runbook_name"),
            diagnosis=data.get("diagnosis"),
            root_cause=data.get("root_cause"),
            confidence=data.get("confidence", 0.0),
            escalation_required=data.get("escalation_required", False),
            restart_safe=data.get("restart_safe"),
        )

    async def pending_steps(self, triage_id: str | None = None) -> list[dict[str, Any]]:
        """List pending investigation steps."""
        params = {}
        if triage_id:
            params["triage_id"] = triage_id
        return await self._request("GET", "/ops/runbooks/steps/pending", params=params)

    # -- Graph queries --

    async def blast_radius(self, service: str) -> dict[str, Any]:
        """Get blast radius for a service."""
        return await self._request("GET", f"/ops/graph/blast-radius/{service}")

    async def dependency_chain(self, service: str) -> dict[str, Any]:
        """Get upstream dependency chain for a service."""
        return await self._request("GET", f"/ops/graph/dependency-chain/{service}")

    # -- Problems --

    async def list_problems(self, *, status: str | None = None) -> list[dict[str, Any]]:
        """List problem records."""
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        return await self._request("GET", "/ops/problems", params=params)

    # -- Trust ledger --

    async def trust_ledger(self) -> list[dict[str, Any]]:
        """Get all trust ledger entries."""
        return await self._request("GET", "/ops/trust")

    async def trust_tier(self, action_type: str) -> dict[str, Any]:
        """Get trust tier for a specific action type."""
        return await self._request("GET", f"/ops/trust/{action_type}")

    # -- Discovery --

    async def config_drift(self) -> dict[str, Any]:
        """Check config drift — declared vs running state."""
        return await self._request("GET", "/ops/discovery/drift")

    async def collect_connections(self) -> dict[str, Any]:
        """Trigger on-demand Layer 2 connection collection."""
        return await self._request("POST", "/ops/discovery/collect")

    # -- Graph queries --

    async def graph_stats(self) -> dict[str, Any]:
        """Get graph node and edge counts."""
        return await self._request("GET", "/ops/graph/stats")

    async def correlated_gpu(self, host: str, gpu_index: int) -> dict[str, Any]:
        """Get services sharing a specific GPU."""
        return await self._request(
            "GET",
            "/ops/graph/correlated-gpu",
            params={"host": host, "gpu_index": gpu_index},
        )

    async def expiring_cis(self, days: int = 30) -> dict[str, Any]:
        """Get CIs expiring within N days."""
        return await self._request("GET", "/ops/graph/expiring-cis", params={"days": days})

    # -- Knowledge --

    async def search_knowledge(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Search operational knowledge base."""
        return await self._request("GET", "/ops/knowledge/search", params={"query": query, "limit": limit})

    async def ingest_knowledge(
        self,
        text: str,
        *,
        source: str = "corvus-sdk",
        doc_type: str = "insight",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ingest knowledge into the operational memory."""
        return await self._request(
            "POST",
            "/ops/knowledge/ingest",
            json={"text": text, "source": source, "doc_type": doc_type, "metadata": metadata or {}},
        )

    # -- Gaps --

    async def gap_summary(self) -> dict[str, Any]:
        """Get open operational gaps."""
        return await self._request("GET", "/ops/gaps")

    async def gap_sweep(self) -> dict[str, Any]:
        """Run gap detection sweep."""
        return await self._request("POST", "/ops/gaps/sweep")

    # -- Metrics --

    async def metrics(self) -> dict[str, Any]:
        """Get operational dashboard metrics."""
        return await self._request("GET", "/ops/metrics")

    async def compliance_audit(
        self, *, since: str | None = None, source: str | None = None
    ) -> dict[str, Any]:
        """Run compliance audit."""
        params: dict[str, str] = {}
        if since:
            params["since"] = since
        if source:
            params["source"] = source
        return await self._request("GET", "/ops/metrics/compliance", params=params)
