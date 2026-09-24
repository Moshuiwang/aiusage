-- Migration 0012: Record historical limit windows for quota analytics over time.
-- limit_windows only stores the latest status per (source_id, provider, window).
-- limit_window_history preserves every observed snapshot.

CREATE TABLE IF NOT EXISTS limit_window_history (
  source_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  window TEXT NOT NULL,
  used_percent REAL NOT NULL,
  remaining_percent REAL NOT NULL,
  reset_at TEXT NOT NULL,
  window_duration_minutes INTEGER NOT NULL,
  source_type TEXT NOT NULL,
  confidence TEXT NOT NULL,
  status TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (source_id, provider, window, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_limit_window_history_lookup
  ON limit_window_history (source_id, provider, window, observed_at DESC);

-- Backfill from existing limit_windows rows
INSERT OR IGNORE INTO limit_window_history (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at, recorded_at
)
SELECT source_id, provider, window, used_percent, remaining_percent, reset_at,
       window_duration_minutes, source_type, confidence, status, observed_at, last_seen_at
FROM limit_windows;
