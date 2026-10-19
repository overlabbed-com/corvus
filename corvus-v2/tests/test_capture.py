"""WP5's tests — the dual-precision atomicity, the bounded store, the
persisted replay, the re-decide substrate, the non-blocking append.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.canonical import request_hash
from corvus.capture import CaptureStore


def _row(rh="rh-1", **over):
    row = {"request_hash": rh, "site_id": "C1",
           "answer_full": {"member": "GO", "probabilities": {"GO": 0.9}},
           "answer_consumed": {"band": "proceed", "confidence_band": "proceed"},
           "state": {"target": "db"}, "facts": {},
           "engine_version": "1.1.0", "weights_version": "w1",
           "catalog_version": "c1"}
    row.update(over)
    return row


def test_dual_precision_atomic():
    """The dual-precision rows: answer_full + answer_consumed in ONE row —
    atomic by construction; no window where one form exists without the
    other (R-SEC-15's precision split at the store layer)."""
    store = CaptureStore()
    assert store.enqueue(_row()) == "recorded"
    rows = store.by_request_hash("rh-1")
    assert len(rows) == 1
    assert rows[0]["answer_full"]["member"] == "GO"
    assert rows[0]["answer_consumed"]["band"] == "proceed"


def test_bounded_store_drops_oldest_and_counts():
    """THE BOUNDED STORE: the capture cannot be the disk-filler — the cap
    enforced at insert, the overflow drops OLDEST-FIRST, the
    capture_dropped counter screams (B4)."""
    store = CaptureStore(max_rows=3)
    for i in range(5):
        store.enqueue(_row(rh=f"rh-{i}"))
    stats = store.stats()
    assert stats["rows"] == 3
    assert stats["dropped"] == 2
    # The OLDEST dropped: rh-0 and rh-1 are gone; rh-4 survives.
    assert store.by_request_hash("rh-0") == []
    assert store.by_request_hash("rh-4") != []


def test_replay_index_persists_across_restart():
    """F10: the replay index lives in the same SQLite WAL — a restart (a
    new store instance on the same file) does NOT wipe the replay; the
    retried key hits the cached response, the duplicate rows become
    recognizable."""
    db = "/tmp/corvus-spike-replay.db"
    Path(db).unlink(missing_ok=True)
    store1 = CaptureStore(db_path=db)
    response = {"answers": {"C1": {"answer": "proceed"}}, "request_hash": "rh-x"}
    store1.replay_put("key-1", response)
    del store1  # the "restart"
    store2 = CaptureStore(db_path=db)
    hit = store2.replay_lookup("key-1")
    assert hit == response
    assert store2.replay_lookup("key-missing") is None
    Path(db).unlink(missing_ok=True)


def test_redecide_substrate_byte_identical():
    """R-SEC-16: the row stores state + facts + the site definitions in the
    CANONICAL form — the re-decision reconstructs byte-identical inputs
    (the shadow re-scoring's exact-input substrate; the same-base control
    for the weight comparison)."""
    store = CaptureStore()
    state = {"target": "db", "recent_severity": "critical"}
    facts = {"inventory": {"value": [], "provenance_class": "attested"}}
    sites = [{"site_id": "C1", "type": "choice", "criteria": {"GO": "g"}}]
    rh = request_hash(state, facts, sites)
    store.enqueue(_row(rh=rh, state=state, facts=facts, sites=sites))
    rows = store.by_request_hash(rh)
    reconstructed = request_hash(rows[0]["state"], rows[0]["facts"], rows[0]["sites"])
    assert reconstructed == rh, "the re-decide reconstructs byte-identical inputs"


def test_enqueue_is_nonblocking_fast():
    """B4: the decision path never notices — the enqueue returns the status
    immediately (the bounded store's insert is bounded-latency; the
    production spool adds the writer thread as the deployment concern)."""
    store = CaptureStore()
    started = time.monotonic()
    for i in range(50):
        store.enqueue(_row(rh=f"rh-{i}"))
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"50 enqueues took {elapsed:.2f}s — the decision path would notice"


def test_duplicate_request_hash_rows_recognized():
    """F10's duplicate rows: the same request_hash solved twice (the
    replay-cache loss) → the rows are RECOGNIZABLE (the by_request_hash
    query returns both, flagged by their presence — not investigated)."""
    store = CaptureStore()
    store.enqueue(_row(rh="rh-dup"))
    store.enqueue(_row(rh="rh-dup"))
    rows = store.by_request_hash("rh-dup")
    assert len(rows) == 2, "the duplicates are recognized, not deduped silently"
