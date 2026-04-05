"""Elastic/OpenSearch SIEM adapter.

Forwards OCSF events via the Bulk Index API.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from src.siem.base import SIEMAdapter

logger = logging.getLogger(__name__)


class ElasticAdapter(SIEMAdapter):
    """Forward OCSF events to Elasticsearch or OpenSearch."""

    name = "elastic"

    def __init__(
        self,
        url: str = "",
        api_key: str = "",
        index_prefix: str = "corvus-ocsf",
        username: str = "",
        password: str = "",
    ):
        super().__init__()
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._index_prefix = index_prefix
        self._username = username
        self._password = password

    def is_configured(self) -> bool:
        return bool(self._url and (self._api_key or (self._username and self._password)))

    def _index_name(self) -> str:
        """Generate time-based index name."""
        date = datetime.now(UTC).strftime("%Y.%m.%d")
        return f"{self._index_prefix}-{date}"

    async def _send(self, ocsf_event: dict[str, Any]) -> bool:
        index = self._index_name()
        # Bulk API format: action line + document line
        action = json.dumps({"index": {"_index": index}})
        doc = json.dumps(ocsf_event, default=str)
        body = f"{action}\n{doc}\n"

        headers: dict[str, str] = {"Content-Type": "application/x-ndjson"}
        if self._api_key:
            headers["Authorization"] = f"ApiKey {self._api_key}"

        auth = None
        if self._username and self._password and not self._api_key:
            auth = (self._username, self._password)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._url}/_bulk",
                content=body,
                headers=headers,
                auth=auth,
                timeout=15,
            )
            if resp.status_code in (200, 201):
                result = resp.json()
                if not result.get("errors", True):
                    return True
                logger.warning("Elastic bulk had errors: %s", result)
                return False

            logger.warning(
                "Elastic forward failed: status=%d body=%s",
                resp.status_code,
                resp.text,
            )
            return False
