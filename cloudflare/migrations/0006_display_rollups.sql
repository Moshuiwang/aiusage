CREATE TABLE IF NOT EXISTS usage_hourly_rollups (
  bucket_start TEXT NOT NULL, bucket_end TEXT NOT NULL, source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL, os_user TEXT NOT NULL, ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL, agent TEXT NOT NULL, client TEXT NOT NULL,
  attribution_confidence TEXT NOT NULL, provenance TEXT NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
  cache_creation_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL,
  reasoning_output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
  event_count INTEGER NOT NULL, session_count INTEGER NOT NULL, fact_count INTEGER NOT NULL,
  PRIMARY KEY (bucket_start, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance)
);
CREATE TABLE IF NOT EXISTS usage_daily_rollups (
  date TEXT NOT NULL, bucket_start TEXT NOT NULL, bucket_end TEXT NOT NULL, source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL, os_user TEXT NOT NULL, ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL, agent TEXT NOT NULL, client TEXT NOT NULL,
  attribution_confidence TEXT NOT NULL, provenance TEXT NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
  cache_creation_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL,
  reasoning_output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
  event_count INTEGER NOT NULL, session_count INTEGER NOT NULL, fact_count INTEGER NOT NULL,
  PRIMARY KEY (date, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance)
);
CREATE INDEX IF NOT EXISTS idx_usage_hourly_rollups_bucket ON usage_hourly_rollups(bucket_start);
CREATE INDEX IF NOT EXISTS idx_usage_daily_rollups_date ON usage_daily_rollups(date);

INSERT OR REPLACE INTO usage_hourly_rollups (
  bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
  reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
)
SELECT window_start, max(window_end), source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
       attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
       sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*)
FROM usage_hourly_facts
GROUP BY window_start, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance;

INSERT OR REPLACE INTO usage_daily_rollups (
  date, bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
  reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
)
SELECT substr(window_start, 1, 10), substr(window_start, 1, 10) || 'T00:00:00+08:00',
       substr(window_start, 1, 10) || 'T23:59:59+08:00', source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
       attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
       sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*)
FROM usage_hourly_facts
GROUP BY substr(window_start, 1, 10), source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance;
