INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status) VALUES
  (1, '2026-06-03T11:30:00+08:00', 'Asia/Shanghai', 'value-parity', 'ok'),
  (2, '2026-06-03T11:31:00+08:00', 'Asia/Shanghai', 'value-parity', 'ok'),
  (3, '2026-06-03T10:00:00+08:00', 'Asia/Shanghai', 'value-parity', 'partial'),
  (4, '2026-06-03T08:30:00+08:00', 'Asia/Shanghai', 'value-parity', 'ok');

INSERT INTO source_reports (
  id, run_id, source_id, report_type, command, status, ccusage_version,
  first_period, last_period, error_type, error_message
) VALUES
  (1, 1, 'mac-local', 'daily', 'seed.sql', 'ok', NULL, '2026-05-29', '2026-06-03', NULL, NULL),
  (2, 2, 'linux-dev-bob', 'daily', 'seed.sql', 'ok', NULL, '2026-05-15', '2026-06-03', NULL, NULL),
  (3, 3, 'workstation-cara', 'daily', 'seed.sql', 'failed', NULL, '2026-06-01', '2026-06-01', 'provider_failed', 'Antigravity provider unavailable'),
  (4, 4, 'mac-mini-dan', 'daily', 'seed.sql', 'ok', NULL, '2026-04-10', '2026-04-10', NULL, NULL);

INSERT INTO source_report_states (
  source_id, collected_at, report_type, command, status, ccusage_version,
  first_period, last_period, error_type, error_message
)
SELECT source_id, collected_at, report_type, command, status, ccusage_version,
       first_period, last_period, error_type, error_message
FROM (
  SELECT
    r.source_id, c.collected_at, r.report_type, r.command, r.status,
    r.ccusage_version, r.first_period, r.last_period, r.error_type, r.error_message,
    ROW_NUMBER() OVER (
      PARTITION BY r.source_id
      ORDER BY c.collected_at DESC, r.id DESC
    ) AS row_rank
  FROM source_reports r
  JOIN collection_runs c ON r.run_id = c.id
)
WHERE row_rank = 1;

INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at) VALUES
  ('mac-local', 'macbook-pro', 'macbook-pro', 'alice', 'darwin', '2026-05-29T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev-bob', 'linux-dev', 'linux-dev', 'bob', 'linux', '2026-05-15T09:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('workstation-cara', 'workstation-9', 'workstation-9', 'cara', 'windows', '2026-06-01T09:00:00+08:00', '2026-06-03T10:00:00+08:00'),
  ('mac-mini-dan', 'mac-mini', 'mac-mini', 'dan', 'darwin', '2026-04-10T09:00:00+08:00', '2026-06-03T11:32:00+08:00');

INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'macbook-pro', 'macbook-pro', 'darwin', '2026-05-29T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev', 'linux-dev', 'linux-dev', 'linux', '2026-05-15T09:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('workstation-9', 'workstation-9', 'workstation-9', 'windows', '2026-06-01T09:00:00+08:00', '2026-06-03T10:00:00+08:00'),
  ('mac-mini', 'mac-mini', 'mac-mini', 'darwin', '2026-04-10T09:00:00+08:00', '2026-06-03T11:32:00+08:00');

INSERT INTO os_identities (machine_id, os_user, display_name, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'alice', 'macbook-pro · alice', '2026-05-29T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev', 'bob', 'linux-dev · bob', '2026-05-15T09:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('workstation-9', 'cara', 'workstation-9 · cara', '2026-06-01T09:00:00+08:00', '2026-06-03T10:00:00+08:00'),
  ('mac-mini', 'dan', 'mac-mini · dan', '2026-04-10T09:00:00+08:00', '2026-06-03T11:32:00+08:00');

INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at) VALUES
  ('claude', 'claude-main', 'Claude Team', 'Claude Team', 'pro', '2026-05-29T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('codex', 'codex-main', 'Codex Team', 'Codex Team', 'pro', '2026-04-10T09:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('antigravity', 'ag-main', 'Antigravity Lab', 'Antigravity Lab', 'team', '2026-06-01T09:00:00+08:00', '2026-06-03T10:00:00+08:00');

INSERT INTO usage_daily (
  source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, total_tokens, total_cost, metadata_json, raw_json, first_seen_at, last_seen_at
) VALUES
  ('mac-local', '2026-06-03', 'claude', 2200, 600, 200, 100, 3100, 1.23, '{"machine":"macbook-pro","host":"macbook-pro","account":"alice","platform":"darwin"}', '{"seed":"mac-local-2026-06-03"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev-bob', '2026-06-03', 'codex', 1000, 500, 100, 0, 1600, 0.72, '{"machine":"linux-dev","host":"linux-dev","account":"bob","platform":"linux"}', '{"seed":"linux-dev-bob-2026-06-03"}', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('workstation-cara', '2026-06-01', 'antigravity', 700, 300, 50, 50, 1100, 0.44, '{"machine":"workstation-9","host":"workstation-9","account":"cara","platform":"windows"}', '{"seed":"workstation-cara-2026-06-01"}', '2026-06-01T10:00:00+08:00', '2026-06-03T10:00:00+08:00'),
  ('mac-local', '2026-05-29', 'claude', 1200, 500, 300, 0, 2000, 0.84, '{"machine":"macbook-pro","host":"macbook-pro","account":"alice","platform":"darwin"}', '{"seed":"mac-local-2026-05-29"}', '2026-05-29T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev-bob', '2026-05-15', 'codex', 1600, 900, 500, 0, 3000, 1.50, '{"machine":"linux-dev","host":"linux-dev","account":"bob","platform":"linux"}', '{"seed":"linux-dev-bob-2026-05-15"}', '2026-05-15T12:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('mac-mini-dan', '2026-04-10', 'codex', 800, 400, 100, 0, 1300, 0.61, '{"machine":"mac-mini","host":"mac-mini","account":"dan","platform":"darwin"}', '{"seed":"mac-mini-dan-2026-04-10"}', '2026-04-10T12:00:00+08:00', '2026-06-03T11:32:00+08:00');

INSERT INTO usage_daily_models (
  source_id, date, agent, model_name, input_tokens, output_tokens,
  cache_creation_tokens, cache_read_tokens, total_tokens, cost, raw_json, first_seen_at, last_seen_at
) VALUES
  ('mac-local', '2026-06-03', 'claude', 'claude-sonnet', 1600, 400, 100, 50, 2150, 0.86, '{"seed":"claude-sonnet"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('mac-local', '2026-06-03', 'claude', 'claude-opus', 600, 200, 100, 50, 950, 0.37, '{"seed":"claude-opus"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev-bob', '2026-06-03', 'codex', 'gpt-5', 1000, 500, 100, 0, 1600, 0.72, '{"seed":"gpt-5-today"}', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('workstation-cara', '2026-06-01', 'antigravity', 'ag-coder', 700, 300, 50, 50, 1100, 0.44, '{"seed":"ag-coder"}', '2026-06-01T10:00:00+08:00', '2026-06-03T10:00:00+08:00'),
  ('mac-local', '2026-05-29', 'claude', 'claude-sonnet', 1200, 500, 300, 0, 2000, 0.84, '{"seed":"claude-sonnet-week"}', '2026-05-29T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev-bob', '2026-05-15', 'codex', 'gpt-5', 1600, 900, 500, 0, 3000, 1.50, '{"seed":"gpt-5-month"}', '2026-05-15T12:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('mac-mini-dan', '2026-04-10', 'codex', 'gpt-4.1', 800, 400, 100, 0, 1300, 0.61, '{"seed":"gpt-4.1-all"}', '2026-04-10T12:00:00+08:00', '2026-06-03T11:32:00+08:00');

INSERT INTO usage_hourly (
  source_id, hour, agent, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, total_tokens, total_cost, metadata_json, raw_json, first_seen_at, last_seen_at
) VALUES
  ('mac-local', '2026-06-03T09:00:00+08:00', 'claude', 2200, 600, 200, 100, 3100, 1.23, '{"machine":"macbook-pro","host":"macbook-pro","account":"alice","platform":"darwin"}', '{"seed":"hourly-mac"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev-bob', '2026-06-03T10:00:00+08:00', 'codex', 1000, 500, 100, 0, 1600, 0.72, '{"machine":"linux-dev","host":"linux-dev","account":"bob","platform":"linux"}', '{"seed":"hourly-linux"}', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');

INSERT INTO usage_hourly_facts (
  fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
  session_count, attribution_confidence, provenance, account_evidence_json, metadata_json,
  first_seen_at, last_seen_at
) VALUES
  ('fact-mac-20260603-09', 'mac-local', 'macbook-pro', 'alice', 'claude', 'claude-main', 'claude', 'cli', '2026-06-03T09:00:00+08:00', '2026-06-03T10:00:00+08:00', 'Asia/Shanghai', 2200, 600, 200, 100, 0, 3100, 1.23, 4, 2, 'observed', 'seed', '{"source":"seed"}', '{"seed":"fact-mac-today"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('fact-linux-20260603-10', 'linux-dev-bob', 'linux-dev', 'bob', 'codex', 'codex-main', 'codex', 'cli', '2026-06-03T10:00:00+08:00', '2026-06-03T11:00:00+08:00', 'Asia/Shanghai', 1000, 500, 100, 0, 25, 1600, 0.72, 3, 1, 'observed', 'seed', '{"source":"seed"}', '{"seed":"fact-linux-today"}', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('fact-workstation-20260601-10', 'workstation-cara', 'workstation-9', 'cara', 'antigravity', 'ag-main', 'antigravity', 'desktop', '2026-06-01T10:00:00+08:00', '2026-06-01T11:00:00+08:00', 'Asia/Shanghai', 700, 300, 50, 50, 0, 1100, 0.44, 2, 1, 'inferred', 'seed', '{"source":"seed"}', '{"seed":"fact-workstation-week"}', '2026-06-01T10:00:00+08:00', '2026-06-03T10:00:00+08:00'),
  ('fact-mac-20260529-09', 'mac-local', 'macbook-pro', 'alice', 'claude', 'claude-main', 'claude', 'cli', '2026-05-29T09:00:00+08:00', '2026-05-29T10:00:00+08:00', 'Asia/Shanghai', 1200, 500, 300, 0, 0, 2000, 0.84, 3, 1, 'observed', 'seed', '{"source":"seed"}', '{"seed":"fact-mac-week"}', '2026-05-29T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('fact-linux-20260515-12', 'linux-dev-bob', 'linux-dev', 'bob', 'codex', 'codex-main', 'codex', 'cli', '2026-05-15T12:00:00+08:00', '2026-05-15T13:00:00+08:00', 'Asia/Shanghai', 1600, 900, 500, 0, 40, 3000, 1.50, 5, 2, 'observed', 'seed', '{"source":"seed"}', '{"seed":"fact-linux-month"}', '2026-05-15T12:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('fact-mini-20260410-12', 'mac-mini-dan', 'mac-mini', 'dan', 'codex', 'codex-main', 'codex', 'cli', '2026-04-10T12:00:00+08:00', '2026-04-10T13:00:00+08:00', 'Asia/Shanghai', 800, 400, 100, 0, 15, 1300, 0.61, 2, 1, 'observed', 'seed', '{"source":"seed"}', '{"seed":"fact-mini-all"}', '2026-04-10T12:00:00+08:00', '2026-06-03T11:32:00+08:00');

INSERT INTO limit_windows (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at,
  first_seen_at, last_seen_at
) VALUES
  ('codex-main', 'codex', '5h', 42.5, 57.5, '2026-06-03T16:00:00+08:00', 300, 'runtime_api', 'observed', 'ok', '2026-06-03T11:00:00+08:00', '2026-06-03T11:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('codex-main', 'codex', 'week', 64.25, 35.75, '2026-06-10T00:00:00+08:00', 10080, 'runtime_api', 'observed', 'ok', '2026-06-03T11:01:00+08:00', '2026-06-03T11:01:00+08:00', '2026-06-03T11:01:00+08:00'),
  ('claude-main', 'claude', '5h', 0, 0, '2026-06-03T15:00:00+08:00', 300, 'oauth_usage_api', 'missing', 'provider_failed', '2026-06-03T11:02:00+08:00', '2026-06-03T11:02:00+08:00', '2026-06-03T11:02:00+08:00'),
  ('claude-main', 'claude', 'week', 78.25, 21.75, '2026-06-10T00:00:00+08:00', 10080, 'oauth_usage_api', 'observed', 'ok', '2026-06-03T11:03:00+08:00', '2026-06-03T11:03:00+08:00', '2026-06-03T11:03:00+08:00');
