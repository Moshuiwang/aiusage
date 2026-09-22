-- Durable authoritative coverage also protects keys never received before the scan.
CREATE TABLE IF NOT EXISTS usage_reconciliation_ranges (
  source_id TEXT NOT NULL,
  agent TEXT NOT NULL,
  provenance TEXT NOT NULL,
  coverage_start TEXT NOT NULL,
  coverage_end TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (source_id, agent, provenance, coverage_start, coverage_end)
);

-- The queue is marked by canonical fact mutations in the same transaction.
CREATE TABLE IF NOT EXISTS usage_rollup_dirty_days (
  date TEXT NOT NULL PRIMARY KEY
);

CREATE TRIGGER IF NOT EXISTS usage_rollup_dirty_insert
AFTER INSERT ON usage_hourly_facts
BEGIN
  INSERT INTO usage_rollup_dirty_days (date) VALUES (date(NEW.window_start, '+8 hours')) ON CONFLICT(date) DO NOTHING;
END;

CREATE TRIGGER IF NOT EXISTS usage_rollup_dirty_delete
AFTER DELETE ON usage_hourly_facts
BEGIN
  INSERT INTO usage_rollup_dirty_days (date) VALUES (date(OLD.window_start, '+8 hours')) ON CONFLICT(date) DO NOTHING;
END;

CREATE TRIGGER IF NOT EXISTS usage_rollup_dirty_update
AFTER UPDATE ON usage_hourly_facts
WHEN OLD.source_id IS NOT NEW.source_id OR OLD.machine_id IS NOT NEW.machine_id
  OR OLD.os_user IS NOT NEW.os_user OR OLD.ai_provider IS NOT NEW.ai_provider
  OR OLD.ai_account_id IS NOT NEW.ai_account_id OR OLD.agent IS NOT NEW.agent
  OR OLD.client IS NOT NEW.client OR OLD.window_start IS NOT NEW.window_start
  OR OLD.window_end IS NOT NEW.window_end OR OLD.attribution_confidence IS NOT NEW.attribution_confidence
  OR OLD.provenance IS NOT NEW.provenance OR OLD.input_tokens IS NOT NEW.input_tokens
  OR OLD.output_tokens IS NOT NEW.output_tokens OR OLD.cache_creation_tokens IS NOT NEW.cache_creation_tokens
  OR OLD.cache_read_tokens IS NOT NEW.cache_read_tokens OR OLD.reasoning_output_tokens IS NOT NEW.reasoning_output_tokens
  OR OLD.total_tokens IS NOT NEW.total_tokens OR OLD.event_count IS NOT NEW.event_count
  OR OLD.session_count IS NOT NEW.session_count
BEGIN
  INSERT INTO usage_rollup_dirty_days (date) VALUES (date(OLD.window_start, '+8 hours')) ON CONFLICT(date) DO NOTHING;
  INSERT INTO usage_rollup_dirty_days (date) VALUES (date(NEW.window_start, '+8 hours')) ON CONFLICT(date) DO NOTHING;
END;

INSERT INTO usage_reconciliation_ranges
SELECT source_id, agent, provenance, coverage_start, coverage_end, observed_at
FROM source_accuracy
WHERE accuracy_status = 'verified' AND mode = 'full-rescan' AND scan_complete = 1
  AND matching_full_scans >= 2 AND read_errors = 0 AND unresolved_mismatch = 0
  AND julianday(coverage_start) < julianday(coverage_end)
ON CONFLICT DO UPDATE SET observed_at = excluded.observed_at
WHERE julianday(excluded.observed_at) > julianday(usage_reconciliation_ranges.observed_at);

-- Repair any projections left stale by the pre-queue ingest path on the next ingest.
INSERT OR IGNORE INTO usage_rollup_dirty_days (date)
SELECT date(window_start, '+8 hours') FROM usage_hourly_facts
UNION SELECT date(bucket_start, '+8 hours') FROM usage_hourly_rollups
UNION SELECT date FROM usage_daily_rollups;
