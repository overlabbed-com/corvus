"""The decision-engine client: the seam Corvus speaks (ENGINE-CONTRACT.md).

The typed-decision lineage: state in, typed sites, typed answers out with
per-option probabilities, fail-closed at both ends. The client applies the
SITE's fail policy when the engine is unreachable or times out — the
fail-closed sites use their registered fail_default (C1 → CAUTION); the
fail-open sites use theirs. The fleet id rides every call (the SaaS seam).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class DecisionClient:
    def __init__(self, base_url: str, engine_key: str, timeout_ms: int = 2000):
        self.base_url = base_url.rstrip("/")
        self.engine_key = engine_key
        self.timeout_ms = timeout_ms

    def decide(self, fleet_id: str, state: dict, sites: dict[str, dict],
               fail_policies: dict[str, str] | None = None) -> dict[str, Any]:
        """One decision call: the sites in, the typed answers out.

        The fail_policies map (site_id → "fail-closed:DEFAULT" |
        "fail-open:DEFAULT") drives the unreachable-engine behavior: the
        registered fail_default is returned as the answer, and the result
        carries `"degraded": true` so the caller knows the engine did not
        decide.
        """
        url = f"{self.base_url}/v1/fleets/{fleet_id}/decide"
        body = json.dumps({"state": state, "sites": sites,
                           "timeout_ms": self.timeout_ms}).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Authorization": "Bearer " + self.engine_key,
                     "Content-Type": "application/json",
                     "X-Corvus-Principal": "corvus-service"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_ms / 1000 + 1) as resp:
                data = json.loads(resp.read())
                # THE FULL PASS-THROUGH: the request_hash, the capture_status,
                # and the engine block ride to the caller — the client is a
                # transport, not a filter (the request_hash is the cross-store
                # key the caller joins on).
                return {**data, "degraded": False}
        except urllib.error.HTTPError:
            # THE CONTRACT BOUNDARY (the spike finding, 2026-10-19): an HTTP
            # error response (400/404/422/…) is the ENGINE ANSWERING — it is
            # NEVER unreachability, and the fail policy must NOT apply to it.
            # HTTPError subclasses URLError, so without this re-raise the
            # contract errors were being masked as degraded answers — the
            # exact conflation the failure-mode column forbids (the fail
            # policy's trigger is the BUDGET, not the error class).
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # The engine unreachable: apply each site's fail policy.
            answers: dict[str, Any] = {}
            for entry in sites:
                site_id = entry.get("site_id") if isinstance(entry, dict) else entry
                policy = (fail_policies or {}).get(site_id, "fail-closed:UNKNOWN")
                kind, _, default = policy.partition(":")
                answers[site_id] = {
                    "answer": default,
                    "probabilities": {},
                    "degraded": True,
                    "fail_kind": kind,
                    "reason": str(exc)[:200],
                }
            return {"answers": answers, "degraded": True}
