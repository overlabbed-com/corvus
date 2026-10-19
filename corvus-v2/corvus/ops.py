"""WP6 — the fleet scope resolver + WP8 — the observability.

The scope resolver: R-SEC-5's mechanism — the authenticated principal
determines which fleet_id it may address; the payload fleet_id is a
routing key. Unknown fleet → 404; known-but-unauthorized → 404
IDENTICALLY (the existence-hiding: the two responses are
indistinguishable, so the fleet's existence is never disclosed).

The observability: the metrics registry (the counters the deadmen need)
+ the three-state healthz (healthy / degraded / down — advisory only;
the decision path NEVER trusts it, F6's healthwash backstop).
"""
from __future__ import annotations

import threading


class FleetScopeResolver:
    """WP6: authenticate principal → authorize fleet_id → resolve config."""

    def __init__(self, principal_fleets: dict[str, set[str]]):
        # principal → the fleet ids it may address. The production form
        # derives this from the credential (the cert identity = the fleet
        # principal, per the mTLS call); the local posture wires it from
        # the fleet config.
        self._principal_fleets = principal_fleets

    def resolve(self, principal: str, fleet_id: str) -> str:
        """Returns 'allowed' or 'not_found' — NEVER 'unauthorized' (the
        existence-hiding: the unauthorized case is indistinguishable from
        the unknown case)."""
        if fleet_id in self._principal_fleets.get(principal, set()):
            return "allowed"
        return "not_found"


class Metrics:
    """WP8: the counters the deadmen need. The registry is thread-safe and
    exportable as the snapshot (the Prometheus shape's precursor)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, labels: str = "", by: float = 1.0) -> None:
        key = f"{name}{labels}"
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + by

    def set_gauge(self, name: str, labels: str, value: float) -> None:
        key = f"{name}{labels}"
        with self._lock:
            self._gauges[key] = value

    def snapshot(self) -> dict:
        with self._lock:
            return {"counters": dict(self._counters), "gauges": dict(self._gauges)}


class Health:
    """WP8: the three-state healthz — healthy / degraded / down.

    degraded = the self-conformance probe passes but breaches its latency
    SLO. ADVISORY ONLY: the decision path never trusts it (F6's healthwash
    backstop — a client MAY consult healthz to fail-fast, never as the
    decision's authority).
    """

    def __init__(self, latency_slo_ms: float = 5000.0):
        self.latency_slo_ms = latency_slo_ms
        self._recent_latencies: list[float] = []

    def record_latency(self, ms: float) -> None:
        self._recent_latencies.append(ms)
        if len(self._recent_latencies) > 100:
            self._recent_latencies = self._recent_latencies[-100:]

    def state(self, dependencies_up: bool = True) -> dict:
        if not dependencies_up:
            return {"state": "down", "advisory": True}
        if self._recent_latencies:
            p50 = sorted(self._recent_latencies)[len(self._recent_latencies) // 2]
            if p50 > self.latency_slo_ms:
                return {"state": "degraded", "p50_ms": p50,
                        "slo_ms": self.latency_slo_ms, "advisory": True}
        return {"state": "healthy", "advisory": True}
