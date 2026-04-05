"""Splunk HEC SIEM adapter."""

import logging
from typing import Any

import httpx

from src.siem.base import SIEMAdapter

logger = logging.getLogger(__name__)


class SplunkAdapter(SIEMAdapter):
    """Forward OCSF events to Splunk via HTTP Event Collector (HEC)."""

    name = "splunk"

    def __init__(self, url: str = "", token: str = "", index: str = "corvus"):
        super().__init__()
        self._url = url
        self._token = token
        self._index = index

    def is_configured(self) -> bool:
        return bool(self._url and self._token)

    async def _send(self, ocsf_event: dict[str, Any]) -> bool:
        payload = {
            "event": ocsf_event,
            "sourcetype": "corvus:ocsf",
            "index": self._index,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._url}/services/collector/event",
                json=payload,
                headers={"Authorization": f"Splunk {self._token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                return True

            logger.warning(
                "Splunk HEC forward failed: status=%d body=%s",
                resp.status_code,
                resp.text,
            )
            return False
