-- Materialize the latest audit report for each source. The write path uses
-- this table for ingest-time duplicate and supersession decisions, so it no
-- longer scans and sorts source_reports history per request.
CREATE TABLE IF NOT EXISTS source_report_states (
  source_id TEXT PRIMARY KEY,
  collected_at TEXT NOT NULL,
  report_type TEXT NOT NULL,
  command TEXT NOT NULL,
  status TEXT NOT NULL,
  ccusage_version TEXT,
  first_period TEXT,
  last_period TEXT,
  error_type TEXT,
  error_message TEXT
);

INSERT OR REPLACE INTO source_report_states (
  source_id, collected_at, report_type, command, status, ccusage_version,
  first_period, last_period, error_type, error_message
)
SELECT source_id, collected_at, report_type, command, status, ccusage_version,
       first_period, last_period, error_type, error_message
FROM (
  SELECT
    r.source_id,
    c.collected_at,
    r.report_type,
    r.command,
    r.status,
    r.ccusage_version,
    r.first_period,
    r.last_period,
    r.error_type,
    r.error_message,
    ROW_NUMBER() OVER (
      PARTITION BY r.source_id
      ORDER BY c.collected_at DESC, r.id DESC
    ) AS row_rank
  FROM source_reports r
  JOIN collection_runs c ON r.run_id = c.id
)
WHERE row_rank = 1;
