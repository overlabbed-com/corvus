-- Migration 001: Add mesh coordination columns
-- Adds node_id, hlc_timestamp, mesh_sync_status for distributed ops state
-- Corresponds to: Task 2 of 7 — Mesh Core Implementation

-- ops_events: Add mesh coordination
ALTER TABLE ops_events ADD COLUMN node_id TEXT DEFAULT 'local';
ALTER TABLE ops_events ADD COLUMN hlc_timestamp TEXT;
ALTER TABLE ops_events ADD COLUMN mesh_sync_status TEXT DEFAULT 'pending';
ALTER TABLE ops_events ADD COLUMN synced_peers TEXT DEFAULT '[]';

-- ops_changes: Add mesh coordination
ALTER TABLE ops_changes ADD COLUMN node_id TEXT DEFAULT 'local';
ALTER TABLE ops_changes ADD COLUMN hlc_timestamp TEXT;
ALTER TABLE ops_changes ADD COLUMN mesh_sync_status TEXT DEFAULT 'pending';

-- ops_incidents: Add mesh coordination
ALTER TABLE ops_incidents ADD COLUMN node_id TEXT DEFAULT 'local';
ALTER TABLE ops_incidents ADD COLUMN hlc_timestamp TEXT;

-- ops_problems: Add mesh coordination
ALTER TABLE ops_problems ADD COLUMN node_id TEXT DEFAULT 'local';
ALTER TABLE ops_problems ADD COLUMN hlc_timestamp TEXT;

-- ops_cmdb: Add registration tracking (mesh registration differs from sync)
ALTER TABLE ops_cmdb ADD COLUMN node_id TEXT DEFAULT 'local';
ALTER TABLE ops_cmdb ADD COLUMN registered_on TEXT DEFAULT 'local';

-- ops_knowledge: Add indexing source tracking
ALTER TABLE ops_knowledge ADD COLUMN node_id TEXT DEFAULT 'local';
ALTER TABLE ops_knowledge ADD COLUMN indexed_from TEXT;

-- mesh_peers: New table for peer node registry
CREATE TABLE IF NOT EXISTS mesh_peers (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL UNIQUE,
    node_uri TEXT NOT NULL,
    roles TEXT NOT NULL DEFAULT '[]',
    last_heartbeat TEXT,
    status TEXT DEFAULT 'unknown',
    capabilities TEXT DEFAULT '{}',
    registered_at TEXT NOT NULL
);

-- Indexes for mesh operations
CREATE INDEX IF NOT EXISTS idx_mesh_peers_status ON mesh_peers(status);
CREATE INDEX IF NOT EXISTS idx_events_node_hlc ON ops_events(node_id, hlc_timestamp);
