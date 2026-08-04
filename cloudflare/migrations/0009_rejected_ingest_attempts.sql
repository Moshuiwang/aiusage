-- Keep authenticated schema/version rejections visible during staged fleet upgrades.
-- The daily key bounds repeat attempts from one source, while the retention cron
-- removes rows after seven days.
CREATE TABLE IF NOT EXISTS rejected_ingest_attempts (
  source_id_claimed TEXT NOT NULL,
  error_type TEXT NOT NULL,
  path TEXT NOT NULL,
  day TEXT NOT NULL, -- AIUSAGE_TIMEZONE product day, UTC only if the timezone binding is invalid.
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(source_id_claimed, error_type, day)
);

CREATE INDEX IF NOT EXISTS idx_rejected_ingest_attempts_last_seen
  ON rejected_ingest_attempts(last_seen_at);
