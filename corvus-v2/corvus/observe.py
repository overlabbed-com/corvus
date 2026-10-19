"""The observe mode (WP15): the mode lives in the FLEET CONFIG (the engine
is mode-blind — a caller-controlled mode would re-open the verdict-bypass
vector through the front door); the ADAPTER enforces it.

THE F9 FIX: in observe mode the adapter never blocks — so an engine outage
means decisions silently stop being made WHILE ACTIONS CONTINUE. The
capture gap and the action gap diverge silently. The fix: **the observe
mode still records the decision attempt** — the attested store logs
(attempted, engine-unavailable, fail-policy applied) per the refusal/event
class. The observe-mode capture gap becomes VISIBLE instead of silent.

THE COVERAGE ACCRUAL: the observe-mode records count toward the fleet's
coverage meter (the readiness evidence) — "observe fills the meter;
enforce mode spends it". The observe evidence informs (the faster
SUPERVISED review); it never promotes directly (admissibility, Clause 4).

THE TOKEN TRAP (named at design time): observe mode must NOT consume
tokens — the consumption ledger showing issued-but-unconsumed IS the
observe signal. The observe path issues nothing.
"""
from __future__ import annotations

import time


class ObserveMode:
    def __init__(self, store, metrics=None):
        # store: the AttestedStore — the attempt records are chain events
        # (the refusal class: the standalone refusals have their own event
        # id, not a log line).
        self.store = store
        self.metrics = metrics
        self._coverage: dict[tuple, int] = {}

    def record_attempt(self, fleet: str, agent: str, site_id: str,
                       engine_answer: dict | None = None,
                       engine_error: str | None = None,
                       decision_id: str | None = None) -> dict:
        """THE ATTEMPT RECORD: answered (recorded, not enforced) or
        unavailable (the fail-policy applied — VISIBLE, not silent)."""
        if engine_answer is not None:
            record = {"kind": "observe-attempt", "fleet": fleet, "agent": agent,
                      "site_id": site_id, "outcome": "answered",
                      "mode": "observe", "ts": time.time()}
            # THE COVERAGE ACCRUAL: the observe evidence fills the meter.
            key = (fleet, agent, site_id)
            self._coverage[key] = self._coverage.get(key, 0) + 1
        else:
            record = {"kind": "observe-attempt", "fleet": fleet, "agent": agent,
                      "site_id": site_id, "outcome": "engine-unavailable",
                      "fail_policy_applied": True, "mode": "observe",
                      "error": engine_error, "ts": time.time()}
        entry = self.store.append("refusal", record, decision_id=decision_id)
        if self.metrics:
            self.metrics.inc("observe_attempts_total",
                             labels=f'{{site="{site_id}",outcome="'
                                    f'{record["outcome"]}"}}')
        return entry

    def coverage(self, fleet: str, agent: str) -> dict:
        """The coverage meter: the observe records per site — what the
        promotion readiness reads (the paired trial evidence's source)."""
        return {f"{site}": count for (f, a, site), count in self._coverage.items()
                if f == fleet and a == agent}

    def token_issuance_allowed(self) -> bool:
        """THE TOKEN TRAP: the observe mode issues NO tokens — the
        consumption ledger showing issued-but-unconsumed IS the observe
        signal. The enforce flip is the gate that turns issuance on."""
        return False
