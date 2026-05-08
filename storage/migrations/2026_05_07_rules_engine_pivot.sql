-- Migration: drop pre-pivot tables. Schema is then recreated by `schema.sql`.
-- Old data is intentionally NOT migrated:
--   * `agent_logs` is per-LLM-agent runs (different domain than the new `audit_log`).
--   * `trades` had different fields and reason taxonomy.
--   * `signals`/`monitor_actions`/`daily_stats`/`weekly_stats`/`suggestions` are unused.
--
-- This script is only run by `init_db.py` when it detects pre-pivot tables.
-- It drops everything; `schema.sql` then runs and creates the new shape.

BEGIN TRANSACTION;

DROP TABLE IF EXISTS signals;
DROP TABLE IF EXISTS monitor_actions;
DROP TABLE IF EXISTS daily_stats;
DROP TABLE IF EXISTS weekly_stats;
DROP TABLE IF EXISTS suggestions;
DROP TABLE IF EXISTS agent_logs;
DROP TABLE IF EXISTS trades;

COMMIT;
