"""Google Chronicle SIEM adapter.

Forwards OCSF events to Google Chronicle via the Ingestion API.
Chronicle has native OCSF support, so events are forwarded as-is.
"""

import json
import logging
from typing import Any

import httpx

from src.siem.base import SIEMAdapter

logger = logging.getLogger(__name__)


class ChronicleAdapter(SIEMAdapter):
    """Forward OCSF events to Google Chronicle.

    Chronicle natively supports OCSF, so events pass through without
    transformation.
    """

    name = "chronicle"

    def __init__(
        self,
        api_key: str = "",
        customer_id: str = "",
        region: str = "us",
    ):
        super().__init__()
        self._api_key = api_key
        self._customer_id = customer_id
        self._region = region

    def is_configured(self) -> bool:
        return bool(self._api_key and self._customer_id)

    async def _send(self, ocsf_event: dict[str, Any]) -> bool:
        url = (
            f"https://{self._region}-chronicle.googleapis.com"
            f"/v1alpha/projects/{self._customer_id}/locations/{self._region}"
            f"/instances/default/logTypes/OCSF/logs:import"
        )

        body = {
            "inline_source": {
                "log_entries": [
                    {
                        "data": json.dumps(ocsf_event, default=str),
                    }
                ],
            }
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            if resp.status_code in (200, 202):
                return True

            logger.warning(
                "Chronicle forward failed: status=%d body=%s",
                resp.status_code,
                resp.text,
            )
            return False
