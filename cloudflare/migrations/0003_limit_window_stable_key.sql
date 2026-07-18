CREATE TABLE limit_windows_v3 (
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
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(source_id, provider, window)
);

INSERT OR REPLACE INTO limit_windows_v3 (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at,
  first_seen_at, last_seen_at
)
SELECT source_id, provider, window, used_percent, remaining_percent, reset_at,
       window_duration_minutes, source_type, confidence, status, observed_at,
       first_seen_at, last_seen_at
FROM limit_windows
ORDER BY julianday(observed_at) ASC, observed_at ASC;

DROP TABLE limit_windows;
ALTER TABLE limit_windows_v3 RENAME TO limit_windows;
