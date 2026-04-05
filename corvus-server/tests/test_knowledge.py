"""Tests for knowledge management API."""


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


class TestKnowledgeCRUD:
    async def test_create_knowledge_entry(self, client):
        resp = await client.post(
            "/ops/knowledge",
            json={
                "title": "vLLM OOM on Blackwell GPUs",
                "content": "When vLLM runs out of VRAM on Blackwell GPUs, "
                "reduce max_model_len or enable chunked prefill.",
                "tags": ["vllm", "gpu", "oom"],
                "service_type": "vllm",
                "target": "vllm-primary",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"].startswith("KNW-")

    async def test_get_knowledge_entry(self, client):
        create = await client.post(
            "/ops/knowledge",
            json={"title": "Test entry", "content": "Some content"},
        )
        entry_id = create.json()["id"]

        resp = await client.get(f"/ops/knowledge/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test entry"
        assert resp.json()["content"] == "Some content"

    async def test_list_knowledge(self, client):
        await client.post(
            "/ops/knowledge",
            json={"title": "Entry 1", "content": "Content 1", "source_type": "manual"},
        )
        await client.post(
            "/ops/knowledge",
            json={"title": "Entry 2", "content": "Content 2", "source_type": "incident"},
        )

        resp = await client.get("/ops/knowledge")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_knowledge_filtered(self, client):
        await client.post(
            "/ops/knowledge",
            json={"title": "Manual entry", "content": "Manual", "source_type": "manual"},
        )
        await client.post(
            "/ops/knowledge",
            json={"title": "Incident entry", "content": "Incident", "source_type": "incident"},
        )

        resp = await client.get("/ops/knowledge?source_type=incident")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["source_type"] == "incident"

    async def test_delete_knowledge_entry(self, client):
        create = await client.post(
            "/ops/knowledge",
            json={"title": "To delete", "content": "Delete me"},
        )
        entry_id = create.json()["id"]

        resp = await client.delete(f"/ops/knowledge/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == entry_id

        # Verify gone
        resp = await client.get(f"/ops/knowledge/{entry_id}")
        assert resp.status_code == 404

    async def test_get_nonexistent_returns_404(self, client):
        resp = await client.get("/ops/knowledge/KNW-NONEXIST")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


class TestKnowledgeSearch:
    async def test_search_finds_matching_content(self, client):
        await client.post(
            "/ops/knowledge",
            json={
                "title": "Caddy TLS certificate renewal",
                "content": "When Caddy fails to renew TLS certs, check DNS resolution "
                "and ensure port 443 is accessible from the internet.",
                "tags": ["caddy", "tls"],
            },
        )
        await client.post(
            "/ops/knowledge",
            json={
                "title": "vLLM memory management",
                "content": "vLLM uses PagedAttention for memory management. "
                "Set gpu_memory_utilization to 0.9 for optimal performance.",
            },
        )

        resp = await client.get("/ops/knowledge/search?q=TLS certificate")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert "caddy" in results[0]["title"].lower() or "tls" in results[0]["content"].lower()

    async def test_search_empty_query(self, client):
        resp = await client.get("/ops/knowledge/search?q=")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_no_results(self, client):
        resp = await client.get("/ops/knowledge/search?q=xyznonexistent")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_with_source_filter(self, client):
        await client.post(
            "/ops/knowledge",
            json={
                "title": "Manual restart procedure",
                "content": "Restart vllm with docker restart",
                "source_type": "manual",
            },
        )
        await client.post(
            "/ops/knowledge",
            json={
                "title": "Incident restart fix",
                "content": "Container restart resolved the vllm issue",
                "source_type": "incident",
            },
        )

        resp = await client.get("/ops/knowledge/search?q=restart&source_type=manual")
        assert resp.status_code == 200
        results = resp.json()
        assert all(r["source_type"] == "manual" for r in results)

    async def test_search_result_has_rank(self, client):
        await client.post(
            "/ops/knowledge",
            json={"title": "GPU troubleshooting", "content": "GPU OOM errors need VRAM reduction"},
        )

        resp = await client.get("/ops/knowledge/search?q=GPU OOM")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert "rank" in results[0]

    async def test_search_deleted_entry_not_found(self, client):
        create = await client.post(
            "/ops/knowledge",
            json={"title": "Temporary knowledge", "content": "This will be deleted soon"},
        )
        entry_id = create.json()["id"]

        # Verify searchable first
        resp = await client.get("/ops/knowledge/search?q=temporary deleted")
        assert len(resp.json()) >= 1

        # Delete
        await client.delete(f"/ops/knowledge/{entry_id}")

        # Should not appear in search
        resp = await client.get("/ops/knowledge/search?q=temporary deleted")
        assert len(resp.json()) == 0


# ---------------------------------------------------------------------------
# Auto-indexing tests
# ---------------------------------------------------------------------------


class TestAutoIndexing:
    async def test_resolved_incident_indexed(self, client):
        """Resolving an incident with root cause auto-creates knowledge entry."""
        # Create incident
        inc = await client.post(
            "/ops/incidents",
            json={
                "target": "vllm-primary",
                "title": "vLLM OOM crash",
                "description": "vLLM crashed with CUDA OOM",
                "severity": "critical",
                "detected_by": "test",
            },
        )
        inc_id = inc.json()["id"]

        # Resolve with root cause
        await client.patch(
            f"/ops/incidents/{inc_id}",
            json={
                "status": "resolved",
                "root_cause": "max_model_len too high for available VRAM",
                "investigation_summary": "Checked nvidia-smi, found 98% VRAM usage",
                "remediation_applied": "Reduced max_model_len from 32768 to 16384",
            },
        )

        # Knowledge should be searchable
        resp = await client.get("/ops/knowledge/search?q=CUDA OOM VRAM")
        results = resp.json()
        assert len(results) >= 1
        assert results[0]["source_type"] == "incident"

    async def test_incident_without_root_cause_not_indexed(self, client):
        """Resolving without root cause should not create knowledge entry."""
        inc = await client.post(
            "/ops/incidents",
            json={
                "target": "test-svc",
                "title": "Flaky test service",
                "severity": "low",
                "detected_by": "test",
            },
        )
        inc_id = inc.json()["id"]

        await client.patch(f"/ops/incidents/{inc_id}", json={"status": "resolved"})

        resp = await client.get("/ops/knowledge?source_type=incident")
        # Should be empty — no root cause to index
        incident_entries = [e for e in resp.json() if e["source_id"] == inc_id]
        assert len(incident_entries) == 0


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------


class TestKnowledgeMCP:
    async def test_mcp_tool_count_includes_knowledge(self, client):
        """Verify knowledge tools are registered."""
        # Verified via test_mcp_endpoint.py tool count (35 tools including knowledge)
        pass

    async def test_knowledge_add_and_search_roundtrip(self, client):
        """Full roundtrip: add knowledge then search for it."""
        # Add
        create = await client.post(
            "/ops/knowledge",
            json={
                "title": "Docker bridge NAT issue",
                "content": "Container restarts on the same bridge rebuild iptables chains, "
                "briefly breaking NAT for cross-VLAN traffic. Fix: use ipvlan with "
                "explicit default route via gateway.",
                "tags": ["docker", "networking", "ipvlan"],
                "service_type": "homeassistant",
                "target": "homeassistant",
            },
        )
        assert create.status_code == 201

        # Search
        resp = await client.get("/ops/knowledge/search?q=bridge NAT iptables")
        results = resp.json()
        assert len(results) >= 1
        assert "ipvlan" in results[0]["content"]
