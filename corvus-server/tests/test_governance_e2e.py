"""E2E integration tests for the governance distribution pipeline.

Tests the full lifecycle: create entries of various types, filter by
source_type, verify the proposed-vs-governance separation, ordering
via governance_order, and idempotent updates with history tracking.
"""


class TestGovernanceListFilter:
    async def test_filter_returns_only_governance_entries(self, client):
        """Create a mix of entry types; GET ?source_type=governance returns only governance."""
        # Create one of each type
        await client.post(
            "/ops/knowledge",
            json={"title": "Manual note", "content": "Regular note.", "source_type": "manual"},
        )
        await client.post(
            "/ops/knowledge",
            json={"title": "Governance rule", "content": "All changes need approval.", "source_type": "governance"},
        )
        await client.post(
            "/ops/knowledge",
            json={"title": "Proposed rule", "content": "Maybe we should X.", "source_type": "governance-proposed"},
        )

        resp = await client.get("/ops/knowledge", params={"source_type": "governance"})
        assert resp.status_code == 200
        entries = resp.json()

        assert len(entries) == 1
        assert entries[0]["source_type"] == "governance"
        assert entries[0]["title"] == "Governance rule"

    async def test_no_filter_returns_all_types(self, client):
        """Without source_type filter, all entry types are returned."""
        await client.post(
            "/ops/knowledge",
            json={"title": "Manual", "content": "m", "source_type": "manual"},
        )
        await client.post(
            "/ops/knowledge",
            json={"title": "Gov", "content": "g", "source_type": "governance"},
        )
        await client.post(
            "/ops/knowledge",
            json={"title": "Proposed", "content": "p", "source_type": "governance-proposed"},
        )

        resp = await client.get("/ops/knowledge")
        assert resp.status_code == 200
        entries = resp.json()
        types = {e["source_type"] for e in entries}

        assert "manual" in types
        assert "governance" in types
        assert "governance-proposed" in types


class TestGovernancePromotionFlow:
    async def test_proposed_not_in_governance_list(self, client):
        """governance-proposed entries do NOT appear in governance filter results."""
        resp = await client.post(
            "/ops/knowledge",
            json={
                "title": "Proposed best practice",
                "content": "Consider adding health checks to all containers.",
                "source_type": "governance-proposed",
            },
        )
        assert resp.status_code == 201
        proposed_id = resp.json()["id"]

        # Verify it exists via direct GET
        detail = await client.get(f"/ops/knowledge/{proposed_id}")
        assert detail.status_code == 200
        assert detail.json()["source_type"] == "governance-proposed"

        # Verify it does NOT show up under governance filter
        gov_list = await client.get("/ops/knowledge", params={"source_type": "governance"})
        assert gov_list.status_code == 200
        gov_ids = [e["id"] for e in gov_list.json()]
        assert proposed_id not in gov_ids

    async def test_proposed_appears_in_own_filter(self, client):
        """governance-proposed entries appear when filtered by their own type."""
        await client.post(
            "/ops/knowledge",
            json={
                "title": "Proposed rule A",
                "content": "Content A",
                "source_type": "governance-proposed",
            },
        )

        resp = await client.get("/ops/knowledge", params={"source_type": "governance-proposed"})
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["source_type"] == "governance-proposed"


class TestGovernanceOrdering:
    async def test_governance_order_persists_via_patch(self, client):
        """Create two governance entries, set different governance_order, verify persistence."""
        resp1 = await client.post(
            "/ops/knowledge",
            json={"title": "Rule A", "content": "First rule.", "source_type": "governance"},
        )
        id_a = resp1.json()["id"]

        resp2 = await client.post(
            "/ops/knowledge",
            json={"title": "Rule B", "content": "Second rule.", "source_type": "governance"},
        )
        id_b = resp2.json()["id"]

        # Set ordering: Rule B should come first (lower number)
        patch_b = await client.patch(f"/ops/knowledge/{id_b}", json={"governance_order": 10})
        assert patch_b.status_code == 200

        patch_a = await client.patch(f"/ops/knowledge/{id_a}", json={"governance_order": 20})
        assert patch_a.status_code == 200

        # Verify order persists by querying the database directly
        # (the _row_to_dict doesn't include governance_order, so check via SQL)
        from src.database import get_db

        db = await get_db()
        try:
            rows = await db.execute_fetchall(
                "SELECT id, governance_order FROM ops_knowledge WHERE source_type = 'governance' "
                "ORDER BY governance_order",
            )
            assert len(rows) == 2
            # Rule B (order=10) should be first
            assert rows[0][0] == id_b
            assert rows[0][1] == 10
            # Rule A (order=20) should be second
            assert rows[1][0] == id_a
            assert rows[1][1] == 20
        finally:
            await db.close()

    async def test_governance_order_default_value(self, client):
        """New governance entries get the default governance_order (50)."""
        resp = await client.post(
            "/ops/knowledge",
            json={"title": "Default order rule", "content": "Content.", "source_type": "governance"},
        )
        entry_id = resp.json()["id"]

        from src.database import get_db

        db = await get_db()
        try:
            rows = await db.execute_fetchall(
                "SELECT governance_order FROM ops_knowledge WHERE id = ?", (entry_id,)
            )
            assert rows[0][0] == 50
        finally:
            await db.close()


class TestGovernanceIdempotentUpdate:
    async def test_update_creates_two_history_records(self, client):
        """Create a governance entry, PATCH content, verify 2 history records with different hashes."""
        resp = await client.post(
            "/ops/knowledge",
            json={
                "title": "Evolving policy",
                "content": "Version 1: All changes need a design doc.",
                "source_type": "governance",
            },
        )
        assert resp.status_code == 201
        entry_id = resp.json()["id"]

        # First history record was created on insert
        hist1 = await client.get(f"/ops/knowledge/{entry_id}/history")
        assert hist1.status_code == 200
        assert len(hist1.json()) == 1

        # Update content
        patch = await client.patch(
            f"/ops/knowledge/{entry_id}",
            json={"content": "Version 2: All changes need a design doc AND challenge."},
        )
        assert patch.status_code == 200

        # Now should have 2 history records
        hist2 = await client.get(f"/ops/knowledge/{entry_id}/history")
        assert hist2.status_code == 200
        records = hist2.json()
        assert len(records) == 2

        # Hashes must differ (different content)
        hash_1 = records[0]["content_hash"]
        hash_2 = records[1]["content_hash"]
        assert hash_1 != hash_2

        # Both should have changed_by populated
        assert records[0]["changed_by"] is not None
        assert records[1]["changed_by"] is not None

    async def test_same_content_update_still_records_history(self, client):
        """PATCH with identical content still records a history entry (no dedup)."""
        content = "Static policy content."
        resp = await client.post(
            "/ops/knowledge",
            json={"title": "Static policy", "content": content, "source_type": "governance"},
        )
        entry_id = resp.json()["id"]

        # PATCH with same content
        await client.patch(f"/ops/knowledge/{entry_id}", json={"content": content})

        hist = await client.get(f"/ops/knowledge/{entry_id}/history")
        records = hist.json()
        assert len(records) == 2

        # Same content means same hash
        assert records[0]["content_hash"] == records[1]["content_hash"]

    async def test_non_content_patch_does_not_add_history_for_non_governance(self, client):
        """PATCH on a non-governance entry does not record governance history."""
        resp = await client.post(
            "/ops/knowledge",
            json={"title": "Manual note", "content": "Original", "source_type": "manual"},
        )
        entry_id = resp.json()["id"]

        await client.patch(f"/ops/knowledge/{entry_id}", json={"content": "Updated"})

        hist = await client.get(f"/ops/knowledge/{entry_id}/history")
        assert hist.json() == []
