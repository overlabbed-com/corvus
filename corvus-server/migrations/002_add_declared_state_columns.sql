-- Migration 002: Add declared state columns for GitOps drift detection
-- Adds declared_image, declared_healthcheck, declared_env_hash, declared_networks,
-- and last_declared_at to ops_cmdb for comparing running containers against GitOps state.
-- Corresponds to: Task 2 — SQLite Schema Fix (declared_image in drift_detections)

-- ops_cmdb: Add declared state tracking columns
ALTER TABLE ops_cmdb ADD COLUMN declared_image TEXT;
ALTER TABLE ops_cmdb ADD COLUMN declared_healthcheck TEXT;
ALTER TABLE ops_cmdb ADD COLUMN declared_env_hash TEXT;
ALTER TABLE ops_cmdb ADD COLUMN declared_networks TEXT;
ALTER TABLE ops_cmdb ADD COLUMN last_declared_at TEXT;