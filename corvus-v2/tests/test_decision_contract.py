"""The contract fixtures — the v1.1 wire shape against the engine shim.

The spike's corpus, extended for WP1: the sites-as-array (the duplicate
detection), the canonical-form request_hash (the key-order stability), the
quantization (the consumed surface), the idempotency replay, the
facts-shape validation (the probability payloads barred), the
existence-hiding, the provenance-floor rejection — the error-enum coverage
invariant's evidence.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.decisions import DecisionClient  # noqa: E402
from corvus.canonical import request_hash  # noqa: E402

FLEET = "fleet-alpha"
SHIM_PORT = 8934


@pytest.fixture
def client():
    return DecisionClient(base_url=f"http://127.0.0.1:{SHIM_PORT}", engine_key="test-key")


@pytest.fixture
def shim():
    import threading
    import time

    import uvicorn

    from corvus.engine_shim import app
    t = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=SHIM_PORT, log_level="error"),
        daemon=True)
    t.start()
    time.sleep(1.0)
    yield


def _raw_post(body: dict, fleet: str = FLEET, principal: str = "corvus-service"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{SHIM_PORT}/v1/fleets/{fleet}/decide",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json",
                 "X-Corvus-Principal": principal})
    return req


C1_SITE = {"site_id": "C1", "type": "choice", "instructions": "May the actor proceed?",
           "criteria": {"GO": "clean", "CAUTION": "attention", "STOP": "critical"}}


def test_valid_site_returns_typed_answer(client, shim):
    r = client.decide(FLEET, {"target": "db", "trust_tier": "SUPERVISED"}, [C1_SITE])
    assert not r["degraded"]
    a = r["answers"]["C1"]
    assert a["answer"] in {"GO", "CAUTION", "STOP"}
    assert "confidence_band" in a and "provenance" in a
    assert a["provenance"]["request_hash"] == r["request_hash"]


def test_malformed_site_rejected_at_boundary(client, shim):
    from urllib.error import HTTPError
    body = {"state": {}, "sites": [{"site_id": "X", "type": "quantum", "instructions": "x"}]}
    with pytest.raises(HTTPError) as ei:
        urllib.request.urlopen(_raw_post(body), timeout=5)
    assert ei.value.code == 400
    err = json.loads(ei.value.read())["error"]
    assert err["code"] == "unknown_type"


def test_choice_without_criteria_rejected(client, shim):
    from urllib.error import HTTPError
    body = {"state": {}, "sites": [{"site_id": "X", "type": "choice", "instructions": "x"}]}
    with pytest.raises(HTTPError) as ei:
        urllib.request.urlopen(_raw_post(body), timeout=5)
    assert ei.value.code == 400
    assert json.loads(ei.value.read())["error"]["code"] == "choice_without_criteria"


def test_duplicate_site_ids_rejected(client, shim):
    """THE SITES-AS-ARRAY's duplicate detection: a dict cannot express two
    entries with the same id; the array form detects them at the boundary."""
    from urllib.error import HTTPError
    dup = dict(C1_SITE)
    body = {"state": {}, "sites": [C1_SITE, dup]}
    with pytest.raises(HTTPError) as ei:
        urllib.request.urlopen(_raw_post(body), timeout=5)
    assert ei.value.code == 400
    assert json.loads(ei.value.read())["error"]["code"] == "duplicate_site"


def test_request_hash_is_key_order_stable(client, shim):
    """THE CANONICAL-FORM HASH: the same inputs in a different JSON key order
    produce the IDENTICAL request_hash — the replay/re-decide substrate."""
    import hashlib as hl
    s1 = {"target": "db", "recent_severity": "critical"}
    s2 = {"recent_severity": "critical", "target": "db"}
    h1 = request_hash(s1, {}, [C1_SITE])
    h2 = request_hash(s2, {}, [C1_SITE])
    assert h1 == h2
    # And the response's hash matches a locally recomputed one:
    r = client.decide(FLEET, s1, [C1_SITE])
    assert r["request_hash"] == h1


def test_idempotency_key_replays(client, shim):
    """THE IDEMPOTENCY RECOVERY (F5): the same key within the window → the
    cached response + the replay marker — the answered-but-unheard case."""
    body = {"state": {"target": "db"}, "sites": [C1_SITE],
            "idempotency_key": "spike-key-1"}
    r1 = json.loads(urllib.request.urlopen(_raw_post(body), timeout=5).read())
    r2 = json.loads(urllib.request.urlopen(_raw_post(body), timeout=5).read())
    assert "replayed" not in r1
    assert r2.get("replayed") is True
    assert r1["request_hash"] == r2["request_hash"]


def test_probability_in_facts_rejected(client, shim):
    """THE NON-PROPAGATION RULE, enforced at the boundary: a fact carrying a
    probability distribution over a site's enum members is a shape violation —
    the probabilities do not propagate across the DAG."""
    from urllib.error import HTTPError
    body = {"state": {},
            "facts": {"upstream_answer": {"value": {"GO": 0.7, "CAUTION": 0.2, "STOP": 0.1},
                                          "provenance_class": "engine-derived"}},
            "sites": [C1_SITE]}
    with pytest.raises(HTTPError) as ei:
        urllib.request.urlopen(_raw_post(body), timeout=5)
    assert ei.value.code == 400
    assert json.loads(ei.value.read())["error"]["code"] == "probability_in_facts"


def test_quantization_consumed_surface(client, shim):
    """R-SEC-20's split: the wire carries the CONSUMED band (the coarse form);
    the full precision stays inside (the capture's answer_full)."""
    site = {"site_id": "C2", "type": "choice", "instructions": "criticality?",
            "criteria": {"routine": "r", "notable": "n", "critical": "c"}}
    r = client.decide(FLEET, {"recent_severity": "critical"}, [site])
    a = r["answers"]["C2"]
    assert a["answer"] == "critical", "the consumed answer is the BAND (C2's bands are its enum members)"
    assert a["confidence_band"] == "high", "the coarse form rides as the confidence_band"
    # The full precision is NOT on the wire:
    assert "probabilities" not in a


def test_unreachable_engine_applies_fail_policy():
    # No shim on this port: the client applies the site's registered fail policy.
    c = DecisionClient(base_url="http://127.0.0.1:9999", engine_key="k", timeout_ms=300)
    site = dict(C1_SITE)
    r = c.decide("f", {"target": "db"}, [site],
                 fail_policies={"C1": "fail-closed:CAUTION"})
    assert r["degraded"]
    assert r["answers"]["C1"]["answer"] == "CAUTION"


def test_http_errors_are_not_masked_as_unreachable(client, shim):
    """THE SPIKE'S FINDING 2, now a fixture: a contract error (404) from the
    engine PROPAGATES — it is never masked as 'engine unreachable' and the
    fail policy never applies to it (the fail policy's trigger is the
    BUDGET, not the error class)."""
    from urllib.error import HTTPError
    c = DecisionClient(base_url=f"http://127.0.0.1:{SHIM_PORT}", engine_key="test-key")
    with pytest.raises(HTTPError) as ei:
        c.decide("fleet-ghost", {}, [C1_SITE])
    assert ei.value.code == 404


def test_existence_hiding_404_identical(shim):
    """R-SEC-5: the unknown fleet and the known-but-unauthorized fleet get
    404s that are INDISTINGUISHABLE (same code, same body)."""
    bodies = []
    for fid in ("fleet-ghost", "fleet-beta"):  # unknown | known-but-not-ours
        body = {"state": {}, "sites": [C1_SITE]}
        req = _raw_post(body, fleet=fid)
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 404
        bodies.append(ei.value.read())
    assert bodies[0] == bodies[1], "the 404 bodies must be identical (existence-hiding)"


def test_provenance_floor_rejection_structured(shim):
    """The floor-rejection: a fact below the declared minimum class → 400
    with the STRUCTURED payload (the adversarial review's remediation)."""
    body = {"state": {},
            "facts": {"conflict_inventory": {"value": [], "provenance_class": "caller-stated"}},
            "sites": [dict(C1_SITE, required_facts={
                "conflict_inventory": {"min_class": "attested"}})]}
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(_raw_post(body), timeout=5)
    assert ei.value.code == 400
    err = json.loads(ei.value.read())["error"]
    assert err["code"] == "provenance_below_floor"
    assert err["failed_fact_id"] == "conflict_inventory"
    assert err["required_provenance_class"] == "attested"
    assert err["observed_provenance_class"] == "caller-stated"


def test_missing_instructions_rejected(client, shim):
    from urllib.error import HTTPError
    body = {"state": {}, "sites": [{"site_id": "X", "type": "choice",
                                    "criteria": {"GO": "g"}}]}
    with pytest.raises(HTTPError) as ei:
        urllib.request.urlopen(_raw_post(body), timeout=5)
    assert ei.value.code == 400
    assert json.loads(ei.value.read())["error"]["code"] == "missing_instructions"


def test_score_without_scale_rejected(client, shim):
    from urllib.error import HTTPError
    body = {"state": {}, "sites": [{"site_id": "X", "type": "score",
                                    "instructions": "x"}]}
    with pytest.raises(HTTPError) as ei:
        urllib.request.urlopen(_raw_post(body), timeout=5)
    assert ei.value.code == 400
    assert json.loads(ei.value.read())["error"]["code"] == "score_without_scale"
