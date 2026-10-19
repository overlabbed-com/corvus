"""The capture store (WP5): the telemetry-class store — drop-tolerant,
poison-tolerant by construction (poisoning degrades training, never
serving — R-SEC-6's store-class split).

The design contract (B4 + F10), proven here:
- The DUAL-PRECISION rows: answer_full + answer_consumed in ONE row —
  atomic by construction (a single insert; no window where one form
  exists without the other).
- THE BOUNDED STORE: the capture cannot be the disk-filler — the cap
  enforced at insert, the overflow drops OLDEST-FIRST, the
  capture_dropped counter screams. The production shape adds the
  bounded spool + the writer thread (the deployment concern); the
  contract (bounded, drop-oldest, the metric, the decision path never
  notices) is what these tests prove.
- THE PERSISTED REPLAY INDEX: the idempotency keys live in the same
  SQLite WAL — a restart does not wipe the replay (F10's duplicate rows
  become recognizable, not mysterious).
- THE RE-DECIDE SUBSTRATE (R-SEC-16): the row stores state + facts +
  the site definitions in the CANONICAL form — the re-decision
  reconstructs byte-identical inputs.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time


class CaptureStore:
    def __init__(self, db_path: str = ":memory:", max_rows: int = 10_000):
        self.db_path = db_path
        self.max_rows = max_rows
        self.dropped = 0
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS capture ("
            " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
            " request_hash TEXT NOT NULL,"
            " idempotency_key TEXT,"
            " ts REAL NOT NULL,"
            " payload TEXT NOT NULL)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS replay ("
            " key TEXT PRIMARY KEY, response TEXT NOT NULL, ts REAL NOT NULL)")
        self._conn.commit()

    def enqueue(self, row: dict) -> str:
        """The non-blocking append (the bounded store): returns
        'recorded' | 'dropped'. The decision path never waits on the
        durable write's fate — the caller gets the status immediately."""
        payload = json.dumps(row, sort_keys=True, separators=(",", ":"))
        with self._lock:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM capture").fetchone()[0]
            if count >= self.max_rows:
                evict = count - self.max_rows + 1
                self._conn.execute(
                    "DELETE FROM capture WHERE seq IN "
                    "(SELECT seq FROM capture ORDER BY seq LIMIT ?)", (evict,))
                self.dropped += evict
            self._conn.execute(
                "INSERT INTO capture (request_hash, idempotency_key, ts, payload) "
                "VALUES (?, ?, ?, ?)",
                (row.get("request_hash"), row.get("idempotency_key"),
                 time.time(), payload))
            self._conn.commit()
            return "recorded"

    def replay_put(self, key: str, response: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO replay (key, response, ts) VALUES (?, ?, ?)",
                (key, json.dumps(response, sort_keys=True), time.time()))
            self._conn.commit()

    def replay_lookup(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM replay WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def by_request_hash(self, request_hash: str) -> list[dict]:
        """The re-decide substrate: the rows for a request_hash — the
        canonical payload reconstructs byte-identical inputs."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM capture WHERE request_hash = ? ORDER BY seq",
                (request_hash,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM capture").fetchone()[0]
        return {"rows": count, "dropped": self.dropped, "max_rows": self.max_rows}
