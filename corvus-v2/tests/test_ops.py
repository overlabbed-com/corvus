"""WP6 + WP8's tests — the scope resolver's existence-hiding, the metrics,
the three-state healthz (advisory-only by construction).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.ops import FleetScopeResolver, Health, Metrics


def test_scope_resolver_existence_hiding():
    """R-SEC-5: the unauthorized fleet resolves NOT_FOUND — indistinguishable
    from the unknown fleet. The resolver never says 'unauthorized' (that
    would disclose the fleet's existence)."""
    resolver = FleetScopeResolver({"corvus-service": {"fleet-alpha"}})
    assert resolver.resolve("corvus-service", "fleet-alpha") == "allowed"
    assert resolver.resolve("corvus-service", "fleet-ghost") == "not_found"
    assert resolver.resolve("corvus-service", "fleet-beta") == "not_found"  # known-but-not-ours
    assert resolver.resolve("unknown-principal", "fleet-alpha") == "not_found"


def test_metrics_counters_and_snapshot():
    m = Metrics()
    m.inc("capture_dropped")
    m.inc("capture_dropped")
    m.inc("decisions_total", labels='{site="C1"}')
    m.set_gauge("spool_depth", "", 3)
    snap = m.snapshot()
    assert snap["counters"]["capture_dropped"] == 2
    assert snap["counters"]["decisions_total{site=\"C1\"}"] == 1
    assert snap["gauges"]["spool_depth"] == 3


def test_health_three_states():
    h = Health(latency_slo_ms=100.0)
    assert h.state()["state"] == "healthy"
    for ms in [150, 160, 170]:
        h.record_latency(ms)
    assert h.state()["state"] == "degraded"  # the p50 breaches the SLO
    assert h.state(dependencies_up=False)["state"] == "down"
    # ADVISORY ONLY: the state dict carries the advisory flag — the decision
    # path never trusts healthz (F6's healthwash backstop).
    assert h.state()["advisory"] is True
