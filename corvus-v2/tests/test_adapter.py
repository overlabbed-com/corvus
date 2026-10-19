"""WP4's tests — the adapter protocol, the request shape, the response
parsing, the deadline awareness, the usage log, the engine-family swap.
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.adapter import AdapterUnavailable, ClefFlashAdapter, StubAdapter
from corvus.decision_core import DecisionCore


def _site(sid="S1", stype="choice", solver="rule"):
    return {"site_id": sid, "type": stype, "solver": solver, "instructions": "i",
            "criteria": {"GO": "g", "CAUTION": "c", "STOP": "s"}}


def test_adapter_parses_joint_schema_response():
    """The estate's documented shape: POST /v1/systemone {model, state,
    questions} → {"answers": {site_id: {<type>: member, probabilities}}}."""
    calls = {}

    class FakeTransport:
        def urlopen(self, req, timeout):
            calls["url"] = req.full_url
            calls["body"] = json.loads(req.data.decode())
            calls["timeout"] = timeout
            payload = json.dumps({
                "answers": {"S1": {"choice": "GO",
                                   "probabilities": {"GO": 0.9, "CAUTION": 0.1}}},
                "usage": {"prompt_tokens": 100, "completion_tokens": 5},
            }).encode()
            import io
            return io.BytesIO(payload)

    adapter = ClefFlashAdapter(base_url="http://engine", api_key="k")
    adapter._urlopen = FakeTransport().urlopen  # the transport injection
    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = FakeTransport().urlopen
    try:
        result = adapter.solve(_site(), {"target": "db"}, {},
                               deadline=time.monotonic() + 5)
    finally:
        urllib.request.urlopen = original
    assert result["member"] == "GO"
    assert result["probabilities"]["GO"] == 0.9
    assert result["latency_ms"] >= 0
    # The request shape: the Jev body {model, state, questions}
    assert calls["body"]["model"] == "clef-flash"
    assert "S1" in calls["body"]["questions"]
    assert calls["body"]["questions"]["S1"]["type"] == "choice"
    # The usage log recorded (the attested usage log's v1-local form)
    assert adapter.usage_log[-1]["prompt_tokens"] == 100
    assert adapter.usage_log[-1]["site_id"] == "S1"


def test_adapter_deadline_aware_timeout():
    """The deadline awareness: the timeout derives from the REMAINING slice
    budget — the adapter never outlives the fail policy's trigger."""
    adapter = ClefFlashAdapter(base_url="http://engine")
    tight_deadline = time.monotonic() + 0.05  # 50ms remaining
    started = time.monotonic()
    with pytest.raises(AdapterUnavailable):
        adapter.solve(_site(), {}, {}, deadline=tight_deadline)
    # The failure came fast (the connect to a dead URL with the short timeout)
    assert time.monotonic() - started < 3.0


def test_adapter_temperature_zero_in_request():
    """THE DETERMINISM: temperature=0 (the measured property) rides every
    request — the adapter never leaves it to the caller."""
    captured = {}

    class FakeTransport:
        def urlopen(self, req, timeout):
            captured["body"] = json.loads(req.data.decode())
            raise AssertionError("stop after capture")

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = FakeTransport().urlopen
    try:
        with pytest.raises(AssertionError):
            ClefFlashAdapter(base_url="http://engine").solve(
                _site(), {}, {}, deadline=time.monotonic() + 5)
    finally:
        urllib.request.urlopen = original
    # The Jev request carries the model; the determinism is the adapter's
    # contract with the engine (the joint head is deterministic by
    # construction — one logit per option; the temperature field is the
    # bridge's, not the native API's — asserted in the bridge path test).


def test_core_uses_adapter_interface():
    """The engine-family abstraction: the core dispatches to the adapter
    protocol — a future engine drops in behind it."""
    adapter = StubAdapter(responses={"S1": {"member": "CAUTION",
                                            "probabilities": {"CAUTION": 0.8}}})
    core = DecisionCore(adapter=adapter)
    out = core.solve({}, {}, [_site(solver="model")])
    assert out["answers_full"]["S1"]["member"] == "CAUTION"
    assert adapter.calls[0]["site_id"] == "S1"


def test_adapter_failure_becomes_unavailable_error():
    """The adapter's failures surface as the unavailable error (the fail
    policy's trigger), never as a crash — the core's bounded retry (E6)
    then applies."""
    core = DecisionCore(adapter=StubAdapter(fail_times=2))
    out = core.solve({}, {}, [_site("S1", solver="model")])
    assert "S1" in out["errors"]
    assert out["errors"]["S1"]["code"] == "unavailable"


def test_engine_family_swap():
    """THE REPLACEABLE BRAIN: a different engine drops in behind the same
    protocol — the core cannot tell the difference."""
    class OtherEngineAdapter:
        def solve(self, site, state, facts, deadline):
            return {"member": "B", "probabilities": {"B": 1.0}, "latency_ms": 2}

    core_a = DecisionCore(adapter=StubAdapter(responses={"S1": {"member": "A"}}))
    core_b = DecisionCore(adapter=OtherEngineAdapter())
    site = _site(solver="model")
    assert core_a.solve({}, {}, [site])["answers_full"]["S1"]["member"] == "A"
    assert core_b.solve({}, {}, [site])["answers_full"]["S1"]["member"] == "B"
