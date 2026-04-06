"""SQLite database setup and connection management."""

import aiosqlite

from src.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_changes (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    targets TEXT NOT NULL,           -- JSON array
    description TEXT NOT NULL,
    rollback_plan TEXT,
    project TEXT,
    auto_expire INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    completed_at TEXT,
    outcome TEXT,
    authenticated_as TEXT,
    node_id TEXT DEFAULT 'local',
    hlc_timestamp TEXT,
    mesh_sync_status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS ops_events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    target TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    data TEXT NOT NULL DEFAULT '{}',  -- JSON
    related_incident_id TEXT,
    related_change_id TEXT,
    related_problem_id TEXT,
    parent_event_id TEXT,
    authenticated_as TEXT,
    node_id TEXT DEFAULT 'local',
    hlc_timestamp TEXT,
    mesh_sync_status TEXT DEFAULT 'pending',
    synced_peers TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS ops_incidents (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    detected_by TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    severity TEXT NOT NULL DEFAULT 'medium',
    title TEXT NOT NULL,
    description TEXT,
    root_cause TEXT,
    investigation_summary TEXT,
    remediation_applied TEXT,
    resolved_at TEXT,
    resolution_time_minutes INTEGER,
    correlated_to_problem TEXT,
    authenticated_as TEXT,
    node_id TEXT DEFAULT 'local',
    hlc_timestamp TEXT
);

CREATE TABLE IF NOT EXISTS ops_problems (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'identified',
    title TEXT NOT NULL,
    pattern TEXT,
    root_cause TEXT,
    recommended_fix TEXT,
    workaround TEXT,
    correlated_incidents TEXT NOT NULL DEFAULT '[]',  -- JSON array
    workstream TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    assigned_to TEXT,
    node_id TEXT DEFAULT 'local',
    hlc_timestamp TEXT
);

CREATE TABLE IF NOT EXISTS ops_cmdb (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    host TEXT,
    service_type TEXT,
    critical INTEGER NOT NULL DEFAULT 0,
    dependencies TEXT NOT NULL DEFAULT '[]',  -- JSON array
    last_seen TEXT,
    baseline_behavior TEXT NOT NULL DEFAULT '{}',  -- JSON
    alert_policy TEXT NOT NULL DEFAULT 'default',
    created_at TEXT NOT NULL,
    registered_by TEXT,
    node_id TEXT DEFAULT 'local',
    registered_on TEXT DEFAULT 'local'
);

CREATE TABLE IF NOT EXISTS ops_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    result TEXT NOT NULL DEFAULT 'success',
    details TEXT NOT NULL DEFAULT '{}'  -- JSON
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON ops_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_target ON ops_events(target);
CREATE INDEX IF NOT EXISTS idx_events_type ON ops_events(type);
CREATE INDEX IF NOT EXISTS idx_changes_status ON ops_changes(status);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON ops_incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_target ON ops_incidents(target);
CREATE INDEX IF NOT EXISTS idx_problems_status ON ops_problems(status);
CREATE INDEX IF NOT EXISTS idx_problems_pattern ON ops_problems(pattern);
CREATE INDEX IF NOT EXISTS idx_cmdb_service_type ON ops_cmdb(service_type);
CREATE INDEX IF NOT EXISTS idx_cmdb_host ON ops_cmdb(host);
CREATE INDEX IF NOT EXISTS idx_events_related_change ON ops_events(related_change_id);
CREATE INDEX IF NOT EXISTS idx_events_related_incident ON ops_events(related_incident_id);

CREATE TABLE IF NOT EXISTS ops_triage_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    target TEXT NOT NULL,
    service_type TEXT NOT NULL,
    runbook_name TEXT NOT NULL,
    action_type TEXT NOT NULL,
    diagnosis TEXT,
    confidence REAL,
    escalation_required INTEGER DEFAULT 0,
    outcome TEXT DEFAULT 'pending',
    outcome_at TEXT,
    related_incident_id TEXT,
    resolution_time_minutes INTEGER
);

CREATE INDEX IF NOT EXISTS idx_triage_log_action_type ON ops_triage_log(action_type);
CREATE INDEX IF NOT EXISTS idx_triage_log_service_type ON ops_triage_log(service_type);
CREATE INDEX IF NOT EXISTS idx_triage_log_outcome ON ops_triage_log(outcome);

CREATE TABLE IF NOT EXISTS ops_pending_steps (
    id TEXT PRIMARY KEY,
    triage_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    step_type TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',  -- JSON
    timeout INTEGER NOT NULL DEFAULT 30,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, completed, failed, timeout
    output TEXT,  -- JSON
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_steps_triage ON ops_pending_steps(triage_id);
CREATE INDEX IF NOT EXISTS idx_pending_steps_status ON ops_pending_steps(status);

CREATE TABLE IF NOT EXISTS ops_knowledge (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,        -- incident, problem, triage, manual
    source_id TEXT,                   -- FK to source record
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',  -- JSON array
    service_type TEXT,
    target TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    embeddings TEXT,
    indexed_from TEXT,
    node_id TEXT DEFAULT 'local'
);

CREATE INDEX IF NOT EXISTS idx_knowledge_source ON ops_knowledge(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_service_type ON ops_knowledge(service_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_target ON ops_knowledge(target);

CREATE VIRTUAL TABLE IF NOT EXISTS ops_knowledge_fts USING fts5(
    knowledge_id,
    title,
    body,
    tags,
    service_type,
    target
);

CREATE TABLE IF NOT EXISTS ops_trust_ledger (
    action_type TEXT PRIMARY KEY,
    total_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    trust_tier TEXT DEFAULT 'ESCALATE',
    promoted_at TEXT,
    demoted_at TEXT
);

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

CREATE INDEX IF NOT EXISTS idx_mesh_peers_status ON mesh_peers(status);
CREATE INDEX IF NOT EXISTS idx_events_node_hlc ON ops_events(node_id, hlc_timestamp);
CREATE INDEX IF NOT EXISTS idx_knowledge_node_id ON ops_knowledge(node_id);
"""


async def get_db() -> aiosqlite.Connection:
    """Get a database connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db() -> None:
    """Initialize database schema."""
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
    finally:
        await db.close()
