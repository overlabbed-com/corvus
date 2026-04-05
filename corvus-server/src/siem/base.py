"""Abstract SIEM forwarder base class.

All SIEM adapters inherit from SIEMAdapter and implement the forward() method.
The base class provides shared retry logic, dead-letter queue, and metrics.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import deque
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class SIEMAdapter(ABC):
    """Abstract base class for SIEM forwarders.

    Subclasses implement:
    - name: str (adapter identifier)
    - _send(event): actual HTTP call to the SIEM
    """

    name: str = "base"
    max_retries: int = 3
    dead_letter_max: int = 1000

    def __init__(self):
        self._dead_letter: deque[dict[str, Any]] = deque(maxlen=self.dead_letter_max)
        self._stats = {
            "forwarded": 0,
            "failed": 0,
            "retries": 0,
        }

    @abstractmethod
    async def _send(self, ocsf_event: dict[str, Any]) -> bool:
        """Send a single OCSF event to the SIEM.

        Returns True on success, False on failure.
        Should NOT retry — the base class handles retries.
        """

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if this adapter has valid configuration."""

    async def forward(self, ocsf_event: dict[str, Any]) -> bool:
        """Forward an OCSF event with retry and dead-letter handling.

        Returns True if forwarded, False otherwise.
        """
        if not self.is_configured():
            return False

        for attempt in range(self.max_retries):
            try:
                if await self._send(ocsf_event):
                    self._stats["forwarded"] += 1
                    return True
            except Exception as e:
                logger.warning(
                    "SIEM %s forward attempt %d failed: %s",
                    self.name,
                    attempt + 1,
                    e,
                )

            self._stats["retries"] += 1
            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        # All retries exhausted
        self._stats["failed"] += 1
        self._dead_letter.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": ocsf_event,
                "adapter": self.name,
            }
        )
        return False

    def get_stats(self) -> dict[str, Any]:
        """Get forwarding statistics."""
        return {
            "adapter": self.name,
            **self._stats,
            "dead_letter_count": len(self._dead_letter),
            "configured": self.is_configured(),
        }

    def get_dead_letters(self) -> list[dict[str, Any]]:
        """Get dead letter queue contents."""
        return list(self._dead_letter)
