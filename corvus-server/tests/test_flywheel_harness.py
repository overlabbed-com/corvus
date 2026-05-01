"""Test harness for Customer Zero continuous improvement flywheel."""

import pytest


class TestImplementationTracker:
    """Test implementation plan tracking."""

    @pytest.mark.asyncio
    async def test_get_implementation_status(self, client):
        """Test getting implementation status."""
        from src.tasks.implementation_tracker import ImplementationTracker

        tracker = ImplementationTracker()
        status = await tracker.get_implementation_status()

        assert "phases" in status
        assert "overall_progress" in status
        assert status["overall_progress"]["total_stories"] == 32
        assert status["overall_progress"]["completion_percentage"] == 100

    @pytest.mark.asyncio
    async def test_success_criteria_recording(self, client):
        """Test recording success criteria."""
        from src.tasks.implementation_tracker import ImplementationTracker

        tracker = ImplementationTracker()
        criteria = {
            "name": "Test Criteria",
            "achieved": True,
            "timestamp": "2026-04-26T00:00:00Z",
            "metrics": {"value": 100},
        }

        result = await tracker.record_success_criteria(criteria)
        assert result is True


class TestOperationalIssueHarvester:
    """Test operational issue harvesting."""

    @pytest.mark.asyncio
    async def test_harvest_issues(self, client):
        """Test harvesting operational issues."""
        from src.tasks.implementation_tracker import OperationalIssueHarvester

        harvester = OperationalIssueHarvester()
        issues = await harvester.harvest_issues()

        assert isinstance(issues, list)
        # May be empty if no issues present

    @pytest.mark.asyncio
    async def test_create_issue_event(self, client):
        """Test creating issue events."""
        from src.tasks.implementation_tracker import OperationalIssueHarvester

        harvester = OperationalIssueHarvester()
        issue = {
            "type": "test_issue",
            "severity": "warning",
            "description": "Test issue",
            "timestamp": "2026-04-26T00:00:00Z",
        }

        event_id = await harvester.create_issue_event(issue)
        assert event_id.startswith("ISSUE-")


class TestSuccessCriteriaAPI:
    """Test success criteria API endpoints."""

    @pytest.mark.asyncio
    async def test_list_success_criteria(self, client):
        """Test listing success criteria."""
        resp = await client.get("/ops/success-criteria")
        assert resp.status_code == 200

        data = resp.json()
        assert "criteria" in data
        assert "total_weight" in data
        assert len(data["criteria"]) > 0

    @pytest.mark.asyncio
    async def test_get_criteria_status(self, client):
        """Test getting criteria status."""
        resp = await client.get("/ops/success-criteria/status")
        assert resp.status_code == 200

        data = resp.json()
        assert "criteria" in data
        assert "overall_score" in data
        assert "achieved_count" in data
        assert data["achieved_count"] <= data["total_count"]

    @pytest.mark.asyncio
    async def test_harvest_operational_issues(self, client):
        """Test manual issue harvesting."""
        resp = await client.post("/ops/success-criteria/harvest")
        assert resp.status_code == 200

        data = resp.json()
        assert "issues_harvested" in data
        assert "issues" in data

    @pytest.mark.asyncio
    async def test_implementation_status(self, client):
        """Test getting implementation status via API."""
        resp = await client.get("/ops/implementation/status")
        assert resp.status_code == 200

        data = resp.json()
        assert "phases" in data
        assert "overall_progress" in data


class TestContinuousImprovementFlywheel:
    """Test the continuous improvement flywheel."""

    @pytest.mark.asyncio
    async def test_flywheel_cycle(self, client):
        """Test running a flywheel cycle."""
        from src.tasks.implementation_tracker import ContinuousImprovementFlywheel

        flywheel = ContinuousImprovementFlywheel()
        results = await flywheel.run_flywheel_cycle()

        assert "cycle_start" in results
        assert "issues_found" in results
        assert "improvements_created" in results
        assert "success_criteria_checked" in results

    @pytest.mark.asyncio
    async def test_flywheel_creates_improvements(self, client):
        """Test that flywheel creates improvements for critical issues."""
        from src.database import get_db
        from src.tasks.implementation_tracker import ContinuousImprovementFlywheel

        flywheel = ContinuousImprovementFlywheel()

        # Create a mock critical issue
        critical_issue = {
            "type": "critical_test_issue",
            "severity": "critical",
            "description": "Critical test issue",
            "timestamp": "2026-04-26T00:00:00Z",
        }

        # Create improvement from issue
        await flywheel._create_improvement_from_issue(critical_issue)

        # Verify improvement was created
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT COUNT(*) as count FROM ops_problems WHERE pattern LIKE 'issue:critical_test_issue%'"
            )
            row = await cursor.fetchone()
            assert row["count"] >= 1
        finally:
            await db.close()
