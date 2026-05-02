-- Migration 004: SIEM dead-letter queue table + missing composite indexes
--
-- Closes fleet-reliability bridge workplan B3b (migration drift). Two pieces
-- of schema are referenced by code but were never declared in the SCHEMA
-- constant in src/database.py:
--
-- 1. ops_siem_dead_letter — SIEM forwarder retry queue (Story 1.2 per
--    src/siem/forwarder.py:127). The forwarder INSERTs into this table
--    when an SIEM adapter throws after retries; get_dead_letters() and
--    resolve_dead_letter() also reference it.
--
-- 2. Composite indexes (test_db_migration.py:TestMigrationErrorHandling
--    asserts they exist):
--      - idx_events_context  : (timestamp DESC, severity) on ops_events
--      - idx_problems_gap    : composite on ops_problems
--      - idx_triage_analytics: composite on ops_triage_log
--
-- All statements are CREATE IF NOT EXISTS — idempotent against any DB
-- that's manually been patched.

-- ============================================================================
-- ops_siem_dead_letter
-- ============================================================================

CREATE TABLE IF NOT EXISTS ops_siem_dead_letter (
    id              TEXT PRIMARY KEY,
    event_id        TEXT NOT NULL,
    event_type      TEXT,
    event_data      TEXT NOT NULL,
    error           TEXT NOT NULL,
    attempted_at    TEXT NOT NULL,
    attempt_count   INTEGER NOT NULL DEFAULT 1,
    last_adapter    TEXT NOT NULL,
    resolved_at     TEXT,
    resolved_by     TEXT
);

-- Used by get_dead_letters() WHERE resolved_at IS NULL ORDER BY attempted_at DESC
CREATE INDEX IF NOT EXISTS idx_siem_dl_unresolved
    ON ops_siem_dead_letter(attempted_at DESC)
    WHERE resolved_at IS NULL;

-- For lookups by originating event during retry / forensic analysis
CREATE INDEX IF NOT EXISTS idx_siem_dl_event
    ON ops_siem_dead_letter(event_id);

-- ============================================================================
-- Composite indexes referenced by tests but missing from SCHEMA
-- ============================================================================

-- ops_events context queries — most recent events filtered by severity and
-- type (test asserts `timestamp DESC`, `severity`, and `type` all appear in
-- the index SQL).
CREATE INDEX IF NOT EXISTS idx_events_context
    ON ops_events(timestamp DESC, severity, type);

-- ops_problems gap analysis — pair status + pattern for the dashboard
-- queries that group active problems by recurring pattern.
CREATE INDEX IF NOT EXISTS idx_problems_gap
    ON ops_problems(status, pattern);

-- ops_triage_log analytics — pair action_type + outcome for the
-- effectiveness dashboards (already have these as separate indexes; the
-- composite makes the GROUP BY action_type, outcome queries fast).
CREATE INDEX IF NOT EXISTS idx_triage_analytics
    ON ops_triage_log(action_type, outcome);
