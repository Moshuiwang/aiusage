-- Revision watermarks are separate from unchanged facts to avoid rewriting usage/rollups.
-- Retain keys after authoritative deletion so delayed older batches cannot resurrect them.
CREATE TABLE IF NOT EXISTS usage_fact_revisions (
  source_id TEXT NOT NULL,
  agent TEXT NOT NULL,
  client TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL,
  attribution_confidence TEXT NOT NULL,
  provenance TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (source_id, agent, client, window_start, window_end,
               ai_provider, ai_account_id, attribution_confidence, provenance)
);

INSERT INTO usage_fact_revisions
SELECT source_id, agent, coalesce(client, ''), window_start, window_end,
       ai_provider, ai_account_id, attribution_confidence, provenance, last_seen_at
FROM usage_hourly_facts
WHERE 1
ON CONFLICT DO NOTHING;
