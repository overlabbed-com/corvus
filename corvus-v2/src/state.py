"""The shared state: the spine without the mesh (ADR-007).

The embedded SQLite. The ten-table spine's CORE for the prototype: changes,
events, change_targets (the normalized targets — the exact matching the old
LIKE-on-JSON lacked). The mesh columns are gone; the event ordering uses the
HLC. The schema is created idempotently.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_changes (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    description TEXT NOT NULL,
    rollback_plan TEXT,
    auto_expire INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    completed_at TEXT,
    outcome TEXT,
    authenticated_as TEXT
);
CREATE TABLE IF NOT EXISTS change_targets (
    change_id TEXT NOT NULL REFERENCES ops_changes(id),
    target TEXT NOT NULL,
    PRIMARY KEY (change_id, target)
);
CREATE INDEX IF NOT EXISTS idx_change_targets_target ON change_targets(target);
CREATE TABLE IF NOT EXISTS ops_events (
    id TEXT PRIMARY KEY,
    hlc_timestamp TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    target TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    data TEXT NOT NULL DEFAULT '{}',
    related_change_id TEXT,
    authenticated_as TEXT,
    signature TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_target ON ops_events(target);
CREATE INDEX IF NOT EXISTS idx_events_hlc ON ops_events(hlc_timestamp);
CREATE TABLE IF NOT EXISTS ops_trust (
    agent TEXT NOT NULL,
    action_type TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'ESCALATE',
    stats TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (agent, action_type)
);
"""


class State:
    """Thread-safe access to the embedded store."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            self._conn.commit()
            return rows
