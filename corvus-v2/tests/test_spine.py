"""The spine's tests: the HLC ordering, the ingest validation, the conflict
check, the signing. The live behavior the prototype proved, pinned."""
import pytest

from corvus.config import FleetConfig
from corvus.core import CorvusCore, sign_event
from corvus.hlc import HLC
from corvus.state import State


@pytest.fixture
def core():
    cfg = FleetConfig(name="test-fleet", node_id="node-1", api_key="k",
                      custom_event_types=["deploy.canary"])
    return CorvusCore(cfg, State(":memory:"))



def test_hlc_causal_ordering():
    h = HLC("n1")
    a = h.now()
    b = h.now()
    assert a < b


def test_hlc_merge_advances_past_remote():
    n1, n2 = HLC("n1"), HLC("n2")
    remote = n2.now()
    local = n1.now()
    merged = n1.merge(remote)
    assert merged > remote and merged > local


def test_ingest_accepts_builtin_and_custom(core):
    r1 = core.ingest_event({"type": "incident.opened", "target": "db", "severity": "critical"})
    r2 = core.ingest_event({"type": "deploy.canary", "target": "web"})
    assert r1["type"] == "incident.opened" and r2["type"] == "deploy.canary"
    assert r1["signature"] and r2["signature"]


def test_ingest_rejects_unknown_type(core):
    with pytest.raises(ValueError, match="Unknown event type"):
        core.ingest_event({"type": "not.a.type", "target": "x"})


def test_ingest_rejects_missing_target(core):
    with pytest.raises(ValueError, match="target"):
        core.ingest_event({"type": "change.started"})


def test_conflict_check_stops_on_critical_event(core):
    core.ingest_event({"type": "incident.opened", "target": "db", "severity": "critical"})
    r = core.conflict_check("db", action_type="deploy", actor="agent-b")
    assert r["recommendation"] == "STOP"
    assert any("critical" in x for x in r["reasons"])


def test_conflict_check_cautions_on_active_change(core):
    core.open_change({"targets": ["db"], "description": "migration", "created_by": "agent-a"})
    r = core.conflict_check("db", action_type="deploy", actor="agent-b")
    assert r["recommendation"] == "CAUTION"
    assert any("active change" in x for x in r["reasons"])


def test_conflict_check_escalates_on_trust(core):
    r = core.conflict_check("clean-target", action_type="deploy", actor="unknown-agent")
    assert r["recommendation"] == "CAUTION"
    assert r["trust_tier"] == "ESCALATE"


def test_exact_target_matching(core):
    """ADR-007: the normalized targets match EXACTLY — 'web' does not match
    'webhook-service' (the old LIKE-on-JSON's false-positive class)."""
    core.open_change({"targets": ["webhook-service"], "description": "x", "created_by": "a"})
    r = core.conflict_check("web", action_type="deploy", actor="b")
    assert not r["active_changes"]


def test_signing_is_deterministic_and_keyed():
    p = {"a": 1, "b": 2}
    s1 = sign_event(p, "key-1")
    s2 = sign_event(p, "key-1")
    s3 = sign_event(p, "key-2")
    assert s1 == s2 and s1 != s3
