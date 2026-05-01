"""Story 6.2: Feedback loop automation.

Automatically create GitHub issues from high-priority gaps and feed
issues back into the dev pipeline.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)


class FeedbackLoop:
    """Automated feedback loop from Corvus gaps to GitHub issues."""

    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN", "")
        self.github_repo = os.getenv("GITHUB_REPO", "overlabbed-com/corvus")
        self.enabled = bool(self.github_token and self.github_repo)
        self._interval = 3600  # Check every hour

    async def sweep_gaps_and_create_issues(self):
        """Sweep for high-priority gaps and create GitHub issues.

        Story 6.2: Automated feedback loop to dev pipeline.
        """
        if not self.enabled:
            logger.debug("Feedback loop disabled (no GITHUB_TOKEN)")
            return

        from src.tasks.gap_detection import get_gap_summary

        gap_summary = await get_gap_summary()
        gaps = gap_summary.get("recent", [])

        created = 0
        for gap in gaps:
            # Only create issues for critical/high severity gaps
            pattern = gap.get("pattern", "")
            if "security" in pattern or "compliance" in pattern:
                issue_title = f"Gap: {gap.get('title', 'Unknown gap')}"
                issue_body = self._format_gap_issue(gap)

                try:
                    issue_url = await self._create_github_issue(issue_title, issue_body)
                    logger.info(f"Created GitHub issue for gap: {issue_url}")
                    created += 1
                except Exception as e:
                    logger.error(f"Failed to create issue for gap: {e}")

        if created > 0:
            logger.info(f"Created {created} GitHub issues from gaps")

    def _format_gap_issue(self, gap: dict) -> str:
        """Format gap data as GitHub issue body."""
        pattern = gap.get("pattern", "unknown")
        title = gap.get("title", "Unknown")
        workstream = gap.get("workstream", "unrouted")
        created_at = gap.get("created_at", datetime.now(UTC).isoformat())

        body = f"""## Gap Detected

**Pattern**: `{pattern}`
**Title**: {title}
**Workstream**: {workstream}
**Detected**: {created_at}

## Details

This gap was automatically detected by Corvus gap detection.

## Recommended Fix

{gap.get("recommended_fix", "See gap detection logic")}

---
*Automatically created by Corvus feedback loop*
"""
        return body

    async def _create_github_issue(self, title: str, body: str) -> str:
        """Create a GitHub issue."""
        url = f"https://api.github.com/repos/{self.github_repo}/issues"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={"title": title, "body": body},
                headers={
                    "Authorization": f"Bearer {self.github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=10,
            )
            resp.raise_for_status()

            data = resp.json()
            return data.get("html_url", "unknown")


async def run_feedback_loop():
    """Run the feedback loop background task."""
    loop = FeedbackLoop()

    while True:
        try:
            await loop.sweep_gaps_and_create_issues()
        except Exception as e:
            logger.error(f"Feedback loop error: {e}")

        await asyncio.sleep(loop._interval)
