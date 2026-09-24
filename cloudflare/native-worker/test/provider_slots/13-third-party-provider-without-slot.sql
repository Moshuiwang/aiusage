-- Issue #61 跨实现 fixture：第三方 provider（mistral）有 canonical ai_provider，
-- 但固定槽位只有 claude / codex / antigravity 三个，它的用量进不了任何槽位。
-- 这部分 token 必须被单独点名（other_provider_tokens），不能藏进 attributed_tokens
-- 里当作「已展示」，否则 Popover 会出现「槽位加起来对不上标题总量、DTO 却说一切正常」。
-- 固定参考时间 2026-06-03T12:00:00+08:00（Asia/Shanghai），period=today。

INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at) VALUES
  ('mac-local', 'macbook-pro', 'macbook-pro', 'alice', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('workstation-cara', 'workstation-9', 'workstation-9', 'cara', 'windows', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');

INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'macbook-pro', 'macbook-pro', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('workstation-9', 'workstation-9', 'workstation-9', 'windows', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');

INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at) VALUES
  ('claude', 'claude-main', 'Claude Team', 'Claude Team', 'pro', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('mistral', 'mistral-main', 'Mistral Lab', 'Mistral Lab', 'team', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');

INSERT INTO usage_hourly_facts (
  fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
  session_count, attribution_confidence, provenance, metadata_json, first_seen_at, last_seen_at
) VALUES
  ('fact-claude-20260603-09', 'mac-local', 'macbook-pro', 'alice', 'claude', 'claude-main', 'claude', 'cli', '2026-06-03T09:00:00+08:00', '2026-06-03T10:00:00+08:00', 'Asia/Shanghai', 2200, 600, 200, 100, 0, 3100, 1.23, 4, 2, 'observed', 'seed', '{"seed":"claude-today"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('fact-mistral-20260603-10', 'workstation-cara', 'workstation-9', 'cara', 'mistral', 'mistral-main', 'mistral', 'desktop', '2026-06-03T10:00:00+08:00', '2026-06-03T11:00:00+08:00', 'Asia/Shanghai', 700, 300, 50, 50, 0, 1100, 0.44, 2, 1, 'inferred', 'seed', '{"seed":"mistral-today"}', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');
