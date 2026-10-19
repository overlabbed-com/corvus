"""WP3's tests — the dispatch per solver class, the timeout slicing, the
partial success, the dependency composition, the sentinel stamps.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.decision_core import DecisionCore


def _site(sid, solver="rule", criteria=None, **extra):
    s = {"site_id": sid, "type": "choice", "solver": solver,
         "instructions": "spike", "criteria": criteria or {"A": "a", "B": "b"},
         "fail_policy": {"default": {"answer": "B"}}}
    s.update(extra)
    return s


def test_rule_dispatch_uses_registered_rule():
    core = DecisionCore(rules={"S1": lambda s, f, e: ("A", {"A": 0.9, "B": 0.1})})
    out = core.solve({}, {}, [_site("S1")])
    assert out["answers_full"]["S1"]["member"] == "A"
    assert "errors" not in out or not out["errors"]


def test_unregistered_rule_defaults_conservative_and_stamped():
    """The honest default: the conservative floor, marked rule-unregistered —
    never a permissive guess (the spike's finding 1, generalized)."""
    core = DecisionCore()
    out = core.solve({}, {}, [_site("S1", criteria={"A": "a", "B": "b"})])
    assert out["answers_full"]["S1"]["member"] == "B"  # the last = the conservative floor
    assert out["answers_full"]["S1"]["reason"] == "rule-unregistered"


def test_model_without_adapter_is_unavailable_error():
    core = DecisionCore()
    out = core.solve({}, {}, [_site("S1", solver="model")])
    assert "S1" in out["errors"]
    assert out["errors"]["S1"]["code"] == "unavailable"
    assert "fallback-verdict" in out["errors"]["S1"]["verdict_class"]
    assert out["errors"]["S1"]["fail_answer"] == "B"


def test_partial_success_answers_and_errors_coexist():
    """THE ANSWERS∪ERRORS INVARIANT: a slow site times out while the batch's
    other sites answer — the slice isolates it (F3)."""
    def slow_rule(state, facts, entry):
        time.sleep(0.15)
        return ("A", {})
    core = DecisionCore(rules={"SLOW": slow_rule})
    sites = [_site("FAST", criteria={"A": "a", "B": "b"}),
             _site("SLOW", criteria={"A": "a", "B": "b"})]
    out = core.solve({}, {}, sites, budget_ms=100)  # 50ms/site: the slow rule exceeds
    assert "FAST" in out["answers_full"]
    assert "SLOW" in out["errors"]
    assert out["errors"]["SLOW"]["code"] == "timeout"
    assert out["errors"]["SLOW"]["fail_answer"] == "B"


def test_timeout_slice_fail_answer_is_conservative():
    """THE FAIL-CLOSED-TIMEOUT TIGHTENING: the timeout cell's fail answer is
    the registered conservative default, stamped fallback-verdict(timeout) —
    recognizably-not-an-answer, never a permissive value."""
    core = DecisionCore(rules={"S1": lambda s, f, e: time.sleep(0.2) or ("A", {})})
    out = core.solve({}, {}, [_site("S1")], budget_ms=50)
    cell = out["errors"]["S1"]
    assert cell["code"] == "timeout"
    assert cell["fail_answer"] == "B"
    assert "fallback-verdict(timeout)" in cell["verdict_class"]


def test_dependency_failed_composition():
    """THE SENTINEL RULE: the dependent detects its dependency's error and
    abstains with dependency_failed(edge) — the silent substitution never
    happens (the C2-timeout→C1 case, safe by construction)."""
    core = DecisionCore(rules={"DEP": lambda s, f, e: time.sleep(0.2) or ("A", {})})
    dep = _site("DEP")
    dependent = _site("DEP-CONSUMER", depends_on=["DEP"])
    out = core.solve({}, {}, [dep, dependent], budget_ms=100)
    assert "DEP" in out["errors"] and out["errors"]["DEP"]["code"] == "timeout"
    assert "DEP-CONSUMER" in out["errors"]
    cell = out["errors"]["DEP-CONSUMER"]
    assert cell["code"] == "dependency_failed"
    assert cell["failed_dependency_edge"] == "DEP"
    assert "DEP" in cell["reason_class"]


def test_dependency_answered_does_not_fail():
    """The dependency ANSWERED → the consumer proceeds (the sequential rule's
    happy path: the consumed answer becomes a fact with the engine-derived
    provenance)."""
    core = DecisionCore(rules={"DEP": lambda s, f, e: ("A", {})})
    dep = _site("DEP")
    dependent = _site("DEP-CONSUMER", depends_on=["DEP"])
    out = core.solve({}, {}, [dep, dependent])
    assert "DEP-CONSUMER" in out["answers_full"]


def test_bounded_internal_retry():
    """E6: one bounded re-ask on the model path — a transient failure
    recovers; a persistent failure raises the adapter-unavailable error."""
    calls = {"n": 0}

    class FlakyAdapter:
        def solve(self, entry, state, facts, deadline):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return {"member": "A", "probabilities": {"A": 0.9}}

    core = DecisionCore(adapter=FlakyAdapter())
    out = core.solve({}, {}, [_site("S1", solver="model")])
    assert out["answers_full"]["S1"]["member"] == "A"
    assert calls["n"] == 2

    class DeadAdapter:
        def solve(self, entry, state, facts, deadline):
            raise RuntimeError("dead")

    core = DecisionCore(adapter=DeadAdapter())
    out = core.solve({}, {}, [_site("S1", solver="model")])
    assert "S1" in out["errors"] and out["errors"]["S1"]["code"] == "unavailable"


def test_capture_rows_carry_answer_full():
    core = DecisionCore(rules={"S1": lambda s, f, e: ("A", {"A": 0.9})})
    out = core.solve({}, {}, [_site("S1")], request_ref="req-1")
    row = out["capture_rows"][0]
    assert row["site_id"] == "S1"
    assert row["answer_full"]["probabilities"]["A"] == 0.9
    assert row["request_ref"] == "req-1"
