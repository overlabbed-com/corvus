"""WP9 + WP10's tests — the fact composer's statuses and stamps, the
attested store's chain grammar, the chain-walker (mutation-checked).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.attested import AttestedStore  # noqa: E402
from corvus.facts import FactComposer, change_window_source  # noqa: E402


# -- WP9: the fact composer -------------------------------------------------

def test_composer_present_stamps_provenance():
    composer = FactComposer(sources={
        "inventory": lambda spec: {"value": [], "provenance_class": "attested",
                                   "as_of": 1000.0, "source": "the ops ledger"}})
    facts, absent = composer.compose(
        {"facts": {"inventory": {"required": True, "min_class": "attested"}}})
    assert not absent
    f = facts["inventory"]
    assert f["status"] == "present"
    assert f["provenance_class"] == "attested"
    assert f["as_of"] == 1000.0


def test_composer_unknown_never_fabricates():
    """THE CLAUSE-1 DISCRIMINATOR: a fact reports unknown, never fabricates —
    the site's unknown-handling branch fires (a fact says what is true,
    including unknown)."""
    composer = FactComposer(sources={
        "conflict_inventory": lambda spec: {"unknown": "source_unavailable"}})
    facts, absent = composer.compose(
        {"facts": {"conflict_inventory": {"required": True}}})
    assert not absent
    assert facts["conflict_inventory"]["status"] == "unknown"
    assert facts["conflict_inventory"]["value"] is None
    assert facts["conflict_inventory"]["reason"] == "source_unavailable"


def test_composer_stale_stamped_distinctly():
    """THE STALE≠UNKNOWN RULE: a value exists but the W7 horizon expired —
    stamped distinctly (the audit distinguishes 'we didn't know' from 'we
    knew something that expired'); the same handling branch."""
    composer = FactComposer(sources={
        "tier": lambda spec: {"value": "L2", "provenance_class": "attested",
                              "as_of": 100.0}},
        freshness={"tier": 60.0})
    facts, absent = composer.compose({"facts": {"tier": {"required": True}}},
                                     now=1000.0)
    assert facts["tier"]["status"] == "stale"
    assert facts["tier"]["value"] == "L2"  # the value kept, stamped


def test_composer_absent_is_composer_defect():
    """ABSENT = the composer defect (no source registered) — reported to the
    caller → 400 missing_fact → fail-closed, fix the composer. Never
    silently skipped, never fabricated as unknown."""
    composer = FactComposer(sources={})
    facts, absent = composer.compose(
        {"facts": {"required_fact": {"required": True}}})
    assert absent == ["required_fact"]
    assert "required_fact" not in facts


def test_status_view_legible():
    """The observe-mode fold: 'facts: N attested, 0 unknown, 1 stale' — the
    display renders from the stamps, never re-derives."""
    composer = FactComposer(sources={
        "a": lambda s: {"value": 1, "provenance_class": "attested", "as_of": 1000.0},
        "b": lambda s: {"unknown": "down"},
        "c": lambda s: {"value": 2, "provenance_class": "attested", "as_of": 100.0}},
        freshness={"c": 10.0})
    facts, _ = composer.compose({"facts": {"a": {}, "b": {}, "c": {}}}, now=1000.0)
    view = composer.compose_status_view(facts)
    assert view["attested"] == 1
    assert view["unknown"] == 1
    assert view["stale"] == 1


def test_change_window_bounded_projection():
    """M7/M5's pattern: the bounded projection from the calendar (the
    activities overlapping the decision's window, not the whole calendar)
    — one calendar, two consumers."""
    import time as t
    now = t.time()
    calendar = [{"activity": "zfs-scrub", "target": "dp02",
                 "window_start": now - 100, "window_end": now + 3600}]
    source = change_window_source(calendar, target="dp02")
    result = source({})
    assert result["value"]["state"] == "active"
    assert result["provenance_class"] == "computed"


# -- WP10: the attested store + the chain -----------------------------------

def test_chain_append_links_and_hashes():
    store = AttestedStore()
    e1 = store.append("decision", {"site": "C1", "answer": "CAUTION"},
                      decision_id="d-1")
    e2 = store.append("consumption", {"token": "t-1"}, decision_id="d-1")
    assert e2["prev_hash"] == e1["hash"], "linked"
    assert e2["seq"] > e1["seq"]
    ok, findings = store.verify()
    assert ok and not findings


def test_chain_tamper_detectable():
    """THE HONEST RESIDUAL: the tamper-evidence makes tampering DETECTABLE —
    a mutated row breaks the hash chain (the verify fires)."""
    store = AttestedStore(db_path="/tmp/corvus-spike-chain.db")
    Path("/tmp/corvus-spike-chain.db").unlink(missing_ok=True)
    store = AttestedStore(db_path="/tmp/corvus-spike-chain.db")
    store.append("decision", {"site": "C1"}, decision_id="d-1")
    store.append("outcome", {"class": "clean"}, decision_id="d-1")
    # THE TAMPER: mutate the payload behind the store's back (the direct DB)
    store._conn.execute("UPDATE chain SET payload = '{\"site\": \"C2\"}' WHERE seq = 1")
    store._conn.commit()
    ok, findings = store.verify()
    assert not ok, "the tamper is detectable"
    assert any("tampered" in f or "mismatch" in f for f in findings)
    Path("/tmp/corvus-spike-chain.db").unlink(missing_ok=True)


def test_lifecycle_walker_clean():
    store = AttestedStore()
    store.append("decision", {"site": "C1"}, decision_id="d-1")
    store.append("consumption", {"token": "t"}, decision_id="d-1")
    store.append("outcome", {"class": "clean"}, decision_id="d-1")
    ok, findings = store.lifecycle_walk()
    assert ok and not findings


def test_lifecycle_walker_planted_gap_fires():
    """MUTATION-CHECKED (the estate's guard discipline): a planted gap — a
    decision with no follow-up — MUST fire the walker. A walker that
    cannot fail proves nothing."""
    store = AttestedStore()
    store.append("decision", {"site": "C1"}, decision_id="d-gap")
    ok, findings = store.lifecycle_walk()
    assert not ok, "the planted gap fires the walker"
    assert any("no consumption" in f for f in findings)


def test_six_record_classes_closed():
    store = AttestedStore()
    with pytest.raises(AssertionError, match="closed"):
        store.append("diagnosis", {"payload": "x"})  # the evidence lane is NOT a chain class
