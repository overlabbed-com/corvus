"""The decision-engine contract's conformance tests: the fail-closed BOTH
ends, proven against the shim (the fixtures from ENGINE-CONTRACT.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from corvus.decisions import DecisionClient

FLEET = "fleet-alpha"


@pytest.fixture
def client():
    return DecisionClient(base_url="http://127.0.0.1:8934", engine_key="test-key")


@pytest.fixture
def shim():
    import threading
    import time
    import urllib.request

    from corvus.engine_shim import app
    import uvicorn

    t = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=8934, log_level="error"),
        daemon=True)
    t.start()
    time.sleep(1.0)
    yield


def test_valid_site_returns_typed_answer(client, shim):
    r = client.decide(FLEET, {"target": "db", "trust_tier": "SUPERVISED"}, {
        "C1": {"type": "choice",
               "instructions": "May the actor proceed?",
               "criteria": {"GO": "clean", "CAUTION": "attention", "STOP": "critical"}}})
    assert not r["degraded"]
    a = r["answers"]["C1"]
    assert a["answer"] in {"GO", "CAUTION", "STOP"}
    assert abs(sum(a["probabilities"].values()) - 1.0) < 0.01


def test_malformed_site_rejected_at_boundary(client, shim):
    from urllib.error import HTTPError
    import json
    import urllib.request
    body = json.dumps({"state": {}, "sites": {"X": {"type": "quantum", "instructions": "x"}}}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8934/v1/fleets/fleet-alpha/decide", data=body, method="POST",
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json",
                    "X-Corvus-Principal": "corvus-service"})
    with pytest.raises(HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5)
    assert ei.value.code == 400
    assert "unknown type" in json.loads(ei.value.read())["detail"]


def test_choice_without_criteria_rejected(client, shim):
    from urllib.error import HTTPError
    import json
    import urllib.request
    body = json.dumps({"state": {}, "sites": {"X": {"type": "choice", "instructions": "x"}}}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8934/v1/fleets/fleet-alpha/decide", data=body, method="POST",
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json",
                    "X-Corvus-Principal": "corvus-service"})
    with pytest.raises(HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5)
    assert ei.value.code == 400


def test_unreachable_engine_applies_fail_policy():
    # No shim on this port: the client applies the site's registered fail policy.
    c = DecisionClient(base_url="http://127.0.0.1:9999", engine_key="k", timeout_ms=300)
    r = c.decide("fleet-alpha", {"target": "db"}, {
        "C1": {"type": "choice", "instructions": "x", "criteria": {"GO": "g", "CAUTION": "c", "STOP": "s"}}},
        fail_policies={"C1": "fail-closed:CAUTION"})
    assert r["degraded"]
    assert r["answers"]["C1"]["answer"] == "CAUTION"  # the registered fail default


def test_conflict_check_uses_the_engine_when_reachable(core_with_engine):
    core, engine = core_with_engine
    core.ingest_event({"type": "incident.opened", "target": "db", "severity": "critical"})
    r = core.conflict_check("db", action_type="deploy", actor="agent-b")
    assert r["recommendation"] == "STOP"  # the engine's answer drives the decision
    assert not r["engine_degraded"]


def test_conflict_check_degrades_to_caution_when_engine_down(core_with_engine):
    core, engine = core_with_engine
    engine.base_url = "http://127.0.0.1:9999"  # the engine unreachable
    r = core.conflict_check("clean-target", action_type="deploy", actor="agent-b")
    assert r["engine_degraded"]
    assert r["recommendation"] == "CAUTION"  # the registered fail default
    assert any("engine unreachable" in x for x in r["reasons"])


def test_existence_hiding_404_identical(shim):
    """R-SEC-5: the unknown fleet and the known-but-unauthorized fleet get
    404s that are INDISTINGUISHABLE (same code, same body)."""
    import json
    import urllib.error
    import urllib.request
    bodies = []
    for fid in ("fleet-ghost", "fleet-beta"):  # unknown | known-but-not-ours
        body = json.dumps({"state": {}, "sites": {}}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:8934/v1/fleets/{fid}/decide", data=body, method="POST",
            headers={"Authorization": "Bearer test-key", "Content-Type": "application/json",
                     "X-Corvus-Principal": "corvus-service"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 404
        bodies.append(ei.value.read())
    assert bodies[0] == bodies[1], "the 404 bodies must be identical (existence-hiding)"


def test_provenance_floor_rejection_structured(shim):
    """The floor-rejection: a fact below the declared minimum class → 400
    with the STRUCTURED payload (the adversarial review's remediation)."""
    import json
    import urllib.error
    import urllib.request
    body = json.dumps({
        "state": {},
        "facts": {"conflict_inventory": {"value": [], "provenance_class": "caller-stated"}},
        "sites": {"C1": {"type": "choice", "instructions": "x",
                         "criteria": {"GO": "g", "CAUTION": "c", "STOP": "s"},
                         "required_facts": {"conflict_inventory": {"min_class": "attested"}}}},
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8934/v1/fleets/fleet-alpha/decide", data=body, method="POST",
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json",
                 "X-Corvus-Principal": "corvus-service"})
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5)
    assert ei.value.code == 400
    err = json.loads(ei.value.read())["error"]
    assert err["code"] == "provenance_below_floor"
    assert err["failed_fact_id"] == "conflict_inventory"
    assert err["required_provenance_class"] == "attested"
    assert err["observed_provenance_class"] == "caller-stated"
