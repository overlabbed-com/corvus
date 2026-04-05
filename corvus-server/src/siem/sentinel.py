"""Azure Sentinel SIEM adapter.

Forwards OCSF events to Azure Sentinel via the Log Analytics
Data Collector API (HTTP Data Collector).
"""

import hashlib
import hmac
import json
import logging
from base64 import b64decode, b64encode
from datetime import UTC, datetime
from typing import Any

import httpx

from src.siem.base import SIEMAdapter

logger = logging.getLogger(__name__)


class SentinelAdapter(SIEMAdapter):
    """Forward OCSF events to Azure Sentinel / Log Analytics."""

    name = "sentinel"

    def __init__(
        self,
        workspace_id: str = "",
        shared_key: str = "",
        log_type: str = "CorvusOCSF",
    ):
        super().__init__()
        self._workspace_id = workspace_id
        self._shared_key = shared_key
        self._log_type = log_type

    def is_configured(self) -> bool:
        return bool(self._workspace_id and self._shared_key)

    def _build_signature(self, body: str, content_length: int, date_string: str) -> str:
        """Build the Azure Log Analytics authorization signature."""
        string_to_hash = f"POST\n{content_length}\napplication/json\nx-ms-date:{date_string}\n/api/logs"
        decoded_key = b64decode(self._shared_key)
        encoded_hash = b64encode(
            hmac.new(decoded_key, string_to_hash.encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        return f"SharedKey {self._workspace_id}:{encoded_hash}"

    async def _send(self, ocsf_event: dict[str, Any]) -> bool:
        body = json.dumps([ocsf_event], default=str)
        rfc1123_date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
        signature = self._build_signature(body, len(body), rfc1123_date)

        url = f"https://{self._workspace_id}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": signature,
                    "Log-Type": self._log_type,
                    "x-ms-date": rfc1123_date,
                    "time-generated-field": "timestamp",
                },
                timeout=15,
            )
            if resp.status_code in (200, 202):
                return True

            logger.warning(
                "Sentinel forward failed: status=%d body=%s",
                resp.status_code,
                resp.text,
            )
            return False
