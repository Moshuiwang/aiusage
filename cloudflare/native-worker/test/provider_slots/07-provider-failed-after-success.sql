-- Issue #61 跨实现 fixture：成功读到额度之后 provider 又失败了一次。
-- 必须立即 fail closed，不允许继续展示上一次成功读到的百分比。
-- 固定参考时间 2026-06-03T12:00:00+08:00（Asia/Shanghai），period=today。

INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at) VALUES
  ('mac-local', 'macbook-pro', 'macbook-pro', 'alice', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'macbook-pro', 'macbook-pro', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at) VALUES
  ('claude', 'claude-main', 'Claude Team', 'Claude Team', 'pro', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO usage_hourly_facts (
  fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
  session_count, attribution_confidence, provenance, metadata_json, first_seen_at, last_seen_at
) VALUES
  ('fact-claude-20260603-09', 'mac-local', 'macbook-pro', 'alice', 'claude', 'claude-main', 'claude', 'cli', '2026-06-03T09:00:00+08:00', '2026-06-03T10:00:00+08:00', 'Asia/Shanghai', 2200, 600, 200, 100, 0, 3100, 1.23, 4, 2, 'observed', 'seed', '{"seed":"claude-today"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO limit_windows (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at,
  first_seen_at, last_seen_at
) VALUES
  ('claude-main', 'claude', 'week', 78.25, 21.75, '2026-06-10T00:00:00+08:00', 10080, 'oauth_usage_api', 'observed', 'ok', '2026-06-03T11:00:00+08:00', '2026-06-03T11:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('claude-main', 'claude', '5h', 0, 0, '2026-06-03T15:00:00+08:00', 300, 'oauth_usage_api', 'missing', 'provider_failed', '2026-06-03T11:30:00+08:00', '2026-06-03T11:30:00+08:00', '2026-06-03T11:30:00+08:00');
