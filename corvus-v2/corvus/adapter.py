"""The inference adapter (WP4): the C4 component — the ONLY model-aware
component in the engine.

The engine-family abstraction: the Adapter protocol (solve → {member,
probabilities, usage}); a future engine drops in behind it (the
replaceable-brain gain). The ClefFlashAdapter implements it against the
estate's clef-flash engine: POST /v1/systemone (the Jev request: {model,
state, questions} → the answers with the per-option probabilities — the
joint-schema head, no free-form generation, no output parsing).

The determinism: temperature=0 (the measured property). The deadline
awareness: the timeout derives from the REMAINING slice budget (the
budget is the fail policy's trigger — the adapter never outlives it).
The usage log: the tokens recorded per solve (the attested usage log's
v1-local form — the cost observability).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Protocol


class AdapterUnavailable(Exception):
    """The model path could not produce an answer — the fail policy's
    trigger (the availability row of the failure-mode column)."""


class Adapter(Protocol):
    def solve(self, site: dict, state: dict, facts: dict,
              deadline: float) -> dict: ...


class ClefFlashAdapter:
    """The clef-flash engine adapter (the joint-schema decision model)."""

    def __init__(self, base_url: str, model: str = "clef-flash",
                 api_key: str | None = None, min_timeout_s: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.min_timeout_s = min_timeout_s
        self.usage_log: list[dict] = []  # the attested usage log's v1-local form

    def solve(self, site: dict, state: dict, facts: dict,
              deadline: float) -> dict:
        remaining = deadline - time.monotonic()
        timeout_s = max(self.min_timeout_s, remaining)
        site_id = site.get("site_id")
        question = {site_id: {"type": site.get("type"),
                              "instructions": site.get("instructions", ""),
                              "criteria": site.get("criteria")}}
        body = json.dumps({"model": self.model, "state": state,
                           "questions": question}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(f"{self.base_url}/v1/systemone",
                                     data=body, method="POST", headers=headers)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError:
            # The contract errors propagate (the spike's finding 2 — the
            # client-side separation applies to the adapter too).
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailable(str(exc)[:200]) from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        answers = data.get("answers") or {}
        site_answer = answers.get(site_id) or {}
        # The joint-schema answer: the member under the site's type key (the
        # estate's client reads answers[site].get("choice") for a choice
        # site); the probabilities ride alongside.
        member = site_answer.get(site.get("type")) or site_answer.get("choice")
        probabilities = site_answer.get("probabilities") or {}
        if member is None:
            raise AdapterUnavailable(f"the engine returned no member for {site_id!r}")
        # THE USAGE LOG (the attested usage log's v1-local form): the tokens
        # recorded per solve — the cost observability.
        usage = data.get("usage") or {}
        self.usage_log.append({"site_id": site_id, "ts": time.time(),
                               "latency_ms": latency_ms,
                               "prompt_tokens": usage.get("prompt_tokens"),
                               "completion_tokens": usage.get("completion_tokens"),
                               "model": self.model})
        return {"member": member, "probabilities": probabilities,
                "latency_ms": latency_ms, "usage": usage}


class StubAdapter:
    """The test adapter: the recorded responses, no network."""

    def __init__(self, responses: dict[str, dict] | None = None,
                 fail_times: int = 0):
        self.responses = responses or {}
        self.fail_times = fail_times
        self.calls: list[dict] = []

    def solve(self, site: dict, state: dict, facts: dict,
              deadline: float) -> dict:
        self.calls.append({"site_id": site.get("site_id"), "state": state,
                           "deadline_remaining": deadline - time.monotonic()})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("the stub failure")
        member = self.responses.get(site.get("site_id"), {}).get("member")
        if member is None:
            raise AdapterUnavailable("no recorded response")
        return {"member": member,
                "probabilities": self.responses.get(site.get("site_id"), {}).get("probabilities", {}),
                "latency_ms": 1, "usage": {}}
