"""Tests for trust ledger (issue #8)."""

import pytest

from src.database import get_db, init_db
from src.tasks.trust_ledger import (
    TIER_AUTO,
    TIER_ESCALATE,
    TIER_SUPERVISED,
    get_trust_tier,
    record_outcome,
)


@pytest.fixture
async def db():
    """Get a fresh database connection."""
    await init_db()
    conn = await get_db()
    try:
        await conn.execute("DELETE FROM ops_trust_ledger")
        await conn.commit()
        yield conn
    finally:
        await conn.close()


class TestRecordOutcome:
    @pytest.mark.asyncio
    async def test_first_success_creates_entry(self, db):
        """First outcome for an action type should create a ledger entry."""
        await record_outcome("remediation.restart:inference", "success")
        tier = await get_trust_tier("remediation.restart:inference")
        assert tier["total_count"] == 1
        assert tier["success_count"] == 1
        assert tier["trust_tier"] == TIER_ESCALATE

    @pytest.mark.asyncio
    async def test_failure_increments(self, db):
        """Failure should increment failure_count."""
        await record_outcome("remediation.restart:inference", "failure")
        tier = await get_trust_tier("remediation.restart:inference")
        assert tier["failure_count"] == 1
        assert tier["total_count"] == 1

    @pytest.mark.asyncio
    async def test_multiple_outcomes_accumulate(self, db):
        """Multiple outcomes should accumulate correctly."""
        for _ in range(5):
            await record_outcome("remediation.restart:inference", "success")
        await record_outcome("remediation.restart:inference", "failure")
        tier = await get_trust_tier("remediation.restart:inference")
        assert tier["total_count"] == 6
        assert tier["success_count"] == 5
        assert tier["failure_count"] == 1


class TestPromotion:
    @pytest.mark.asyncio
    async def test_promote_after_20_successes(self, db):
        """Should promote from ESCALATE to SUPERVISED after 20+ successes at >95%."""
        for _ in range(20):
            await record_outcome("restart:db", "success")
        tier = await get_trust_tier("restart:db")
        assert tier["trust_tier"] == TIER_SUPERVISED
        assert tier["promoted_at"] is not None

    @pytest.mark.asyncio
    async def test_promote_to_auto(self, db):
        """Should promote from SUPERVISED to AUTO after another 20 successes."""
        # First 20 -> SUPERVISED
        for _ in range(20):
            await record_outcome("restart:proxy", "success")
        # Next 20 -> AUTO (total 40, still >95%)
        for _ in range(20):
            await record_outcome("restart:proxy", "success")
        tier = await get_trust_tier("restart:proxy")
        assert tier["trust_tier"] == TIER_AUTO

    @pytest.mark.asyncio
    async def test_21_successes_is_supervised_not_auto(self, db):
        """21 successes should be SUPERVISED, not AUTO (counters reset on promotion)."""
        for _ in range(21):
            await record_outcome("restart:edge", "success")
        tier = await get_trust_tier("restart:edge")
        assert tier["trust_tier"] == TIER_SUPERVISED

    @pytest.mark.asyncio
    async def test_no_promote_below_threshold(self, db):
        """Should NOT promote if success rate < 95%."""
        for _ in range(18):
            await record_outcome("restart:media", "success")
        for _ in range(2):
            await record_outcome("restart:media", "failure")
        tier = await get_trust_tier("restart:media")
        # 90% success rate -- not enough
        assert tier["trust_tier"] == TIER_ESCALATE

    @pytest.mark.asyncio
    async def test_no_promote_below_count(self, db):
        """Should NOT promote with fewer than 20 executions."""
        for _ in range(19):
            await record_outcome("restart:dns", "success")
        tier = await get_trust_tier("restart:dns")
        assert tier["trust_tier"] == TIER_ESCALATE


class TestDemotion:
    @pytest.mark.asyncio
    async def test_demote_auto_on_failure(self, db):
        """Any failure at AUTO should demote to SUPERVISED."""
        # Promote to AUTO
        for _ in range(40):
            await record_outcome("restart:util", "success")
        tier = await get_trust_tier("restart:util")
        assert tier["trust_tier"] == TIER_AUTO

        # One failure -> demote
        await record_outcome("restart:util", "failure")
        tier = await get_trust_tier("restart:util")
        assert tier["trust_tier"] == TIER_SUPERVISED
        assert tier["demoted_at"] is not None

    @pytest.mark.asyncio
    async def test_no_demote_supervised_on_failure(self, db):
        """Failure at SUPERVISED should NOT demote further."""
        for _ in range(20):
            await record_outcome("restart:iot", "success")
        tier = await get_trust_tier("restart:iot")
        assert tier["trust_tier"] == TIER_SUPERVISED

        await record_outcome("restart:iot", "failure")
        tier = await get_trust_tier("restart:iot")
        # Stays SUPERVISED, not demoted to ESCALATE
        assert tier["trust_tier"] == TIER_SUPERVISED


class TestGetTrustTier:
    @pytest.mark.asyncio
    async def test_unknown_action_type(self, db):
        """Unknown action type should return ESCALATE with zero counts."""
        tier = await get_trust_tier("nonexistent:type")
        assert tier["trust_tier"] == TIER_ESCALATE
        assert tier["total_count"] == 0


from tests.conftest import client  # noqa: F401, E402


class TestTrustAPI:
    @pytest.mark.asyncio
    async def test_get_trust_ledger_empty(self, client):
        """GET /ops/trust should return empty list when no data."""
        resp = await client.get("/ops/trust")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_trust_ledger_with_data(self, client):
        """GET /ops/trust should return ledger entries."""
        await record_outcome("restart:inference", "success")

        resp = await client.get("/ops/trust")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["action_type"] == "restart:inference"

    @pytest.mark.asyncio
    async def test_get_single_trust_tier(self, client):
        """GET /ops/trust/{action_type} should return single entry."""
        await record_outcome("restart:database", "success")

        resp = await client.get("/ops/trust/restart:database")
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "restart:database"
        assert data["trust_tier"] == "ESCALATE"

    @pytest.mark.asyncio
    async def test_get_unknown_trust_tier(self, client):
        """GET /ops/trust/{action_type} for unknown type should return defaults."""
        resp = await client.get("/ops/trust/nonexistent:type")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trust_tier"] == "ESCALATE"
        assert data["total_count"] == 0


class TestTrustIntegration:
    @pytest.mark.asyncio
    async def test_target_status_includes_trust(self, client):
        """Target status should include trust tier info."""
        # Register service
        await client.post(
            "/ops/cmdb/register",
            json={
                "name": "vllm-primary",
                "host": "dockp04",
                "service_type": "inference",
            },
        )

        resp = await client.get("/ops/events/targets/vllm-primary/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "trust_tier" in data

    @pytest.mark.asyncio
    async def test_metrics_include_trust_tiers(self, client):
        """GET /ops/metrics should include trust tier counts."""
        resp = await client.get("/ops/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "trust_tiers" in data
        assert "recent_promotions" in data
