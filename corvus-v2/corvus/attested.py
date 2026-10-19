"""The attested store + the chain grammar (WP10): the evidence class —
the store the whole seam design was aiming at.

THE CHAIN GRAMMAR (four disciplines, stated as the implementation):
1. ATTESTED-WRITE — Corvus-observed only; the store-assigned canonical
   timestamps (caller clocks are claims, never timestamps).
2. LINKED — every member carries prev_hash (the tamper-evident chain).
3. APPEND-ONLY — the only mutation is a tombstone; corrections are new
   events, never edits.
4. CAPACITY-ISOLATED — the chain lives on the evidence path (the
   deployment's storage-class split; the skeleton notes it).

THE SIX RECORD CLASSES (no second-class records): decision · refusal ·
consumption · outcome · escalation_delivery · tombstone.

THE CHAIN-WALKER: walks every decision_id and asserts the lifecycle is
present or explicitly tombstoned (decision → [consumption | refusal |
escalation-delivery] → outcome or supersession). A gap is a FINDING, not
an absence — and the walker is mutation-checked (plant a gap; the walker
must fire), per the estate's guard discipline.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time

RECORD_CLASSES = {"decision", "refusal", "consumption", "outcome",
                  "escalation_delivery", "tombstone"}
LIFECYCLE_FIRST = {"consumption", "refusal", "escalation_delivery"}
LIFECYCLE_LAST = {"outcome", "tombstone"}


class AttestedStore:
    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS chain ("
            " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts REAL NOT NULL,"                # the store-assigned canonical ts
            " record_class TEXT NOT NULL,"
            " decision_id TEXT,"                # the lifecycle join key
            " prev_hash TEXT NOT NULL,"
            " payload TEXT NOT NULL,"
            " hash TEXT NOT NULL)")
        self._conn.commit()
        self._genesis = "0" * 64

    def append(self, record_class: str, payload: dict,
               decision_id: str | None = None) -> dict:
        """The attested-write append. Returns the chain entry."""
        assert record_class in RECORD_CLASSES, \
            f"unknown record class {record_class!r} — the six classes are closed"
        with self._lock:
            prev = self._conn.execute(
                "SELECT hash FROM chain ORDER BY seq DESC LIMIT 1").fetchone()
            prev_hash = prev[0] if prev else self._genesis
            ts = time.time()  # THE STORE-ASSIGNED canonical ts (never caller time)
            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            h = hashlib.sha256(
                f"{prev_hash}|{record_class}|{decision_id}|{ts}|{payload_json}"
                .encode()).hexdigest()
            cur = self._conn.execute(
                "INSERT INTO chain (ts, record_class, decision_id, prev_hash, "
                "payload, hash) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, record_class, decision_id, prev_hash, payload_json, h))
            self._conn.commit()
            return {"seq": cur.lastrowid, "ts": ts, "record_class": record_class,
                    "decision_id": decision_id, "prev_hash": prev_hash,
                    "payload": payload, "hash": h}

    def chain(self, record_class: str | None = None) -> list[dict]:
        with self._lock:
            if record_class:
                rows = self._conn.execute(
                    "SELECT seq, ts, record_class, decision_id, prev_hash, payload, "
                    "hash FROM chain WHERE record_class = ? ORDER BY seq",
                    (record_class,)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT seq, ts, record_class, decision_id, prev_hash, payload, "
                    "hash FROM chain ORDER BY seq").fetchall()
        return [{"seq": r[0], "ts": r[1], "record_class": r[2],
                 "decision_id": r[3], "prev_hash": r[4],
                 "payload": json.loads(r[5]), "hash": r[6]} for r in rows]

    def verify(self) -> tuple[bool, list[str]]:
        """The hash-chain verification: the linked + the append-only
        disciplines, checked. Any tamper (a mutated row, a deleted row,
        a re-order) breaks the chain — DETECTABLE (the honest residual:
        detectable, not impossible)."""
        findings: list[str] = []
        prev_hash = self._genesis
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, ts, record_class, decision_id, prev_hash, payload, "
                "hash FROM chain ORDER BY seq").fetchall()
        for r in rows:
            seq, ts, rc, did, ph, pj, h = r
            if ph != prev_hash:
                findings.append(f"seq {seq}: the prev_hash breaks the link "
                                f"(expected {prev_hash[:12]}…, found {ph[:12]}…)")
            expect = hashlib.sha256(
                f"{ph}|{rc}|{did}|{ts}|{pj}".encode()).hexdigest()
            if expect != h:
                findings.append(f"seq {seq}: the hash mismatch — the record was "
                                f"tampered with")
            prev_hash = h
        return (len(findings) == 0, findings)

    def lifecycle_walk(self) -> tuple[bool, list[str]]:
        """THE CHAIN-WALKER: every decision_id's lifecycle present or
        explicitly tombstoned. A gap is a finding. MUTATION-CHECKED by the
        tests (a planted gap fires the walker)."""
        findings: list[str] = []
        entries = self.chain()
        by_decision: dict[str, list[dict]] = {}
        for e in entries:
            did = e.get("decision_id")
            if did:
                by_decision.setdefault(did, []).append(e)
        for did, dec_entries in by_decision.items():
            classes = [e["record_class"] for e in dec_entries]
            if "decision" not in classes:
                findings.append(f"{did}: lifecycle entries without a decision "
                                f"record (the orphan class: {classes})")
                continue
            has_first = any(c in LIFECYCLE_FIRST for c in classes)
            has_last = any(c in LIFECYCLE_LAST for c in classes)
            if not has_first:
                findings.append(f"{did}: a decision with no consumption/refusal/"
                                f"escalation-delivery — the enforcement gap")
            if not has_last:
                findings.append(f"{did}: a decision with no outcome or "
                                f"supersession — the evidence gap (the M3 "
                                f"family at the chain level)")
        return (len(findings) == 0, findings)
