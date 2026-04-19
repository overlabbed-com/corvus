-- Migration 003: Backfill columns referenced by routers but missing from schema
--
-- Several production DBs were created before columns were added to router
-- code (patterns usage/success tracking, deploy-state tracking in cmdb).
-- These ADD COLUMNs match what the routers query today. All idempotent
-- via IF NOT EXISTS-style suppression in the migration runner.

-- ops_patterns: learned pattern quality + usage tracking
ALTER TABLE ops_patterns ADD COLUMN name TEXT;
ALTER TABLE ops_patterns ADD COLUMN diagnosis TEXT;
ALTER TABLE ops_patterns ADD COLUMN trigger_conditions TEXT DEFAULT '{}';
ALTER TABLE ops_patterns ADD COLUMN source TEXT;
ALTER TABLE ops_patterns ADD COLUMN avg_confidence REAL;
ALTER TABLE ops_patterns ADD COLUMN last_used_at TEXT;
ALTER TABLE ops_patterns ADD COLUMN usage_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ops_patterns ADD COLUMN success_count INTEGER NOT NULL DEFAULT 0;

-- ops_cmdb: deploy attempt tracking (discovery/deploy_manager.py)
ALTER TABLE ops_cmdb ADD COLUMN last_deploy_attempt TEXT;
ALTER TABLE ops_cmdb ADD COLUMN last_deploy_status TEXT;
ALTER TABLE ops_cmdb ADD COLUMN last_deploy_error TEXT;
