"""WP15 + WP16's tests — the observe-mode attempt records (the F9 fix),
the coverage accrual, the token trap, the delivery chain's stages and
deadman, the E1 routing rule.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.attested import AttestedStore
from corvus.delivery import DeliveryChain
from corvus.observe import ObserveMode
from corvus.ops import Metrics

# -- WP15: the observe mode --------------------------------------------------

@pytest.fixture
def observe():
    store = AttestedStore()
    return ObserveMode(store, Metrics()), store


def test_observe_attempt_answered_recorded(observe):
    """The observe mode records the ANSWERED attempt — the decision
    recorded, the action NOT gated (no token issuance)."""
    obs, store = observe
    entry = obs.record_attempt("f", "agent-a", "C1",
                               engine_answer={"member": "GO"})
    classes = [e["record_class"] for e in store.chain()]
    assert "refusal" in classes  # the standalone refusal class carries the attempt
    assert entry["payload"]["outcome"] == "answered"
    assert entry["payload"]["mode"] == "observe"


def test_observe_engine_outage_visible_not_silent(observe):
    """THE F9 FIX: the engine outage in observe mode → the ATTEMPT record
    (attempted, engine-unavailable, fail-policy applied) — the capture gap
    becomes VISIBLE instead of silent (the incident-1 pattern, forbidden
    here by construction)."""
    obs, store = observe
    entry = obs.record_attempt("f", "agent-a", "C1",
                               engine_error="connection refused")
    assert entry["payload"]["outcome"] == "engine-unavailable"
    assert entry["payload"]["fail_policy_applied"] is True
    # The chain event exists — the silence is broken by construction:
    classes = [e["record_class"] for e in store.chain()]
    assert "refusal" in classes


def test_observe_coverage_accrues(observe):
    """THE COVERAGE ACCRUAL: the observe records fill the meter — what the
    promotion readiness reads ('observe fills the meter; enforce mode
    spends it')."""
    obs, _ = observe
    for _ in range(3):
        obs.record_attempt("f", "agent-a", "C1", engine_answer={"member": "GO"})
    coverage = obs.coverage("f", "agent-a")
    assert coverage["C1"] == 3


def test_observe_issues_no_tokens(observe):
    """THE TOKEN TRAP (named at design time): the observe mode issues NO
    tokens — the consumption ledger showing issued-but-unconsumed IS the
    observe signal."""
    obs, _ = observe
    assert obs.token_issuance_allowed() is False


# -- WP16: the delivery chain ------------------------------------------------

@pytest.fixture
def chain():
    store = AttestedStore()
    delivered: list[dict] = []

    def channel(payload):
        delivered.append(payload)
        return True

    return DeliveryChain(store, channel), store, delivered


def test_delivery_chain_stages_are_chain_events(chain):
    """THE STAGES ARE CHAIN EVENTS: queued → delivered — the escalation-
    delivery record class covers the delivery (no second-class records)."""
    dc, store, _ = chain
    dc.submit("esc-1", {"headline": "the 2am escalation"})
    dc.deliver("esc-1")
    stages = [e["payload"]["stage"] for e in store.chain()
              if e["record_class"] == "escalation_delivery"]
    assert "queued" in stages and "delivered" in stages


def test_delivery_failure_queues_for_recovery(chain):
    _dc, store, _delivered = chain
    store2 = store
    dc2 = DeliveryChain(store2, lambda p: (_ for _ in ()).throw(RuntimeError("down")))
    dc2.submit("esc-2", {"headline": "x"})
    result = dc2.deliver("esc-2")
    assert result["status"] == "queued-for-recovery"


def test_delivery_on_recovery_and_deadman(chain):
    """STAGE 3: the deliver-on-recovery retries the queued escalations; the
    ones past the SLO fire the DEADMAN (the alarm IS the signal — silence
    would be the silent decline)."""
    store3 = AttestedStore()
    flaky: list[dict] = []

    def failing_for_z(payload):
        if payload.get("headline") == "z":
            return False  # esc-4's channel is down
        flaky.append(payload)
        return True

    dc3 = DeliveryChain(store3, failing_for_z, slo_s=300.0)
    dc3.submit("esc-3", {"headline": "y"})
    recovered = dc3.deliver_on_recovery()
    assert "esc-3" in recovered
    # THE DEADMAN: an undelivered escalation past the SLO fires — the alarm
    # IS the signal (silence would be the silent decline).
    dc3.submit("esc-4", {"headline": "z"})
    dc3.deliver_on_recovery(now=time.time() + 400)  # past the 300s SLO
    stages = [e["payload"]["stage"] for e in store3.chain()
              if e["record_class"] == "escalation_delivery"]
    assert "deadman-fired" in stages


def test_e1_invalid_routes_to_default_channel():
    """THE E1 ROUTING RULE: 'invalid' is a classification, not a
    destination — the invalid-vocabulary escalations route to the DEFAULT
    HUMAN CHANNEL + alarm."""
    routed: list[dict] = []
    dc = DeliveryChain(AttestedStore(), lambda p: True,
                       default_channel=lambda p: routed.append(p) or True)
    result = dc.route_invalid({"event_type": "nonexistent.vocabulary"})
    assert result["routed"] and result["channel"] == "default-human-channel"
    assert routed
