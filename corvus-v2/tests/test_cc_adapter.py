"""WP13's tests — the CC adapter: the observe mode never blocks, the
enforce gate refuses without the token, the outcome emission is a chain
event, the v1 surface covered.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.attested import AttestedStore
from corvus.cc_adapter import CCAdapter
from corvus.observe import ObserveMode
from corvus.ops import Metrics
from corvus.tokens import VerdictTokenIssuer


class _StubClient:
    """The DecisionClient's stub: the recorded answers, the transport-free."""

    def __init__(self, answer="CAUTION", fail=False):
        self.answer = answer
        self.fail = fail

    def decide(self, fleet, state, sites, fail_policies=None):
        if self.fail:
            raise RuntimeError("connection refused")
        return {"answers": {"C1": {"answer": self.answer}},
                "request_hash": "rh-stub", "degraded": False}


@pytest.fixture
def observe_mode():
    store = AttestedStore()
    return ObserveMode(store, Metrics()), store


def test_observe_mode_never_blocks(observe_mode):
    """THE OBSERVE MODE NEVER BLOCKS: the CAUTION/STOP answer is RECORDED
    and the action PROCEEDS — the exit-0 with the annotation."""
    obs, _ = observe_mode
    adapter = CCAdapter(_StubClient(answer="STOP"), obs, mode="observe")
    result = adapter.pre_tool_use({"tool_name": "Bash",
                                   "tool_input": {"target": "db"}})
    assert result["continue"] is True
    assert result["observe"]["answer"] == "STOP"
    assert result["observe"]["recorded"] is True


def test_observe_engine_outage_records_and_proceeds(observe_mode):
    """THE F9 FIX AT THE ADAPTER: the engine unreachable → the attempt
    recorded (the fail policy applied) and the action proceeds — the gap
    is visible, not silent."""
    obs, store = observe_mode
    adapter = CCAdapter(_StubClient(fail=True), obs, mode="observe")
    result = adapter.pre_tool_use({"tool_name": "Bash",
                                   "tool_input": {"target": "db"}})
    assert result["continue"] is True
    assert result["observe"]["outcome"] == "engine-unavailable"
    classes = [e["record_class"] for e in store.chain()]
    assert "refusal" in classes


def test_ungated_tool_passes_through(observe_mode):
    obs, _ = observe_mode
    adapter = CCAdapter(_StubClient(), obs, mode="observe")
    result = adapter.pre_tool_use({"tool_name": "Read",
                                   "tool_input": {"path": "x"}})
    assert result["continue"] is True
    assert "observe" not in result  # not gated, not recorded as a decision


def test_enforce_without_issuer_fails_closed(observe_mode):
    """THE ENFORCE GATE: the enforce mode without the token issuer → the
    BLOCK (the misconfiguration fails closed — never a bypass)."""
    obs, _ = observe_mode
    adapter = CCAdapter(_StubClient(answer="GO"), obs, mode="enforce",
                        token_issuer=None)
    result = adapter.pre_tool_use({"tool_name": "Bash",
                                   "tool_input": {"target": "db"}})
    assert result["decision"] == "block"


def test_enforce_consumes_verdict_token(observe_mode):
    """THE ENFORCE PATH: the valid verdict → the token issued + consumed →
    the action proceeds; the consumption is a chain event."""
    obs, store = observe_mode
    store.append("decision", {"site": "C1", "answer": "GO"}, decision_id="rh-stub")
    issuer = VerdictTokenIssuer(store, evidence_window_s=60)
    adapter = CCAdapter(_StubClient(answer="GO"), obs, mode="enforce",
                        token_issuer=issuer)
    result = adapter.pre_tool_use({"tool_name": "Bash",
                                   "tool_input": {"target": "db"}})
    assert result["continue"] is True
    assert result["enforce"]["consumed"] is True
    classes = [e["record_class"] for e in store.chain()]
    assert "consumption" in classes


def test_post_tool_use_outcome_is_chain_event(observe_mode):
    """THE OUTCOME EMISSION: the action's outcome lands in the attested
    store as a chain event (the v1 event-emit's role, now chain-membered —
    no second-class records)."""
    obs, store = observe_mode
    adapter = CCAdapter(_StubClient(), obs, mode="observe")
    result = adapter.post_tool_use({"tool_name": "Bash",
                                    "outcome": {"exit": 0, "summary": "deployed"}})
    assert result["recorded"]["seq"] > 0
    classes = [e["record_class"] for e in store.chain()]
    assert "outcome" in classes


def test_v1_surface_covered(observe_mode):
    """THE V1 SURFACE (the decommission archive's inventory): the five hook
    registrations map to the adapter's two handlers + the gated tools."""
    obs, _ = observe_mode
    adapter = CCAdapter(_StubClient(), obs, mode="observe")
    # The v1's PreToolUse(Bash) + PreToolUse(docker/portainer) → the gated tools:
    assert "Bash" in adapter.gated_tools
    assert "DockerRestart" in adapter.gated_tools
    # The v1's PostToolUse → the outcome emission:
    result = adapter.handle("PostToolUse", {"tool_name": "Bash", "outcome": {}})
    assert result["continue"] is True
    # The v1's UserPromptSubmit (the lifecycle classification) → P2's
    # escalation package (the human solver) — the P2 scope, not WP13's.
