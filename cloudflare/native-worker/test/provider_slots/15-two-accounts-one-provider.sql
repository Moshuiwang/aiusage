-- #90 缺口块 12：同一个 provider 下**两个真实账号**都有官方额度窗口。
--
-- 前 14 个场景里同 provider 多 source_id 只出现过一次（08 号的「官方 vs 本地估算」），
-- 从来没有过「两个真实账号」。于是 `selectedLimitSources`（mobile 侧择优）与
-- `bestLimitWindows`（读侧去重）这两条逻辑在测试里**零命中**。
--
-- 择优规则：同 provider 只展示 observed_at 最新的那个账号。不择优的后果是
-- 两个账号的百分比混在一起显示——用户看到的数字既不是 A 的也不是 B 的。
--
-- 本场景：claude-main（11:03 观测，78.25%）与 claude-second（11:30 观测，40%）。
-- 期望：展示 claude-second 那一条，claude-main 不出现在 mobile 的额度窗口里。
-- 固定参考时间 2026-06-03T12:00:00+08:00（Asia/Shanghai），period=today。

INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at) VALUES
  ('mac-local', 'macbook-pro', 'macbook-pro', 'alice', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'macbook-pro', 'macbook-pro', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO os_identities (machine_id, os_user, display_name, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'alice', 'macbook-pro · alice', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

-- 同一个 provider 下的两个账号，都是真实账号（都有 ai_accounts 行）。
INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at) VALUES
  ('claude', 'claude-main', 'Claude Team', 'Claude Team', 'pro', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('claude', 'claude-second', 'Claude Personal', 'Claude Personal', 'pro', '2026-06-03T09:30:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO usage_hourly_facts (
  fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
  session_count, attribution_confidence, provenance, metadata_json, first_seen_at, last_seen_at
) VALUES
  ('fact-claude-20260603-09', 'mac-local', 'macbook-pro', 'alice', 'claude', 'claude-main', 'claude', 'cli', '2026-06-03T09:00:00+08:00', '2026-06-03T10:00:00+08:00', 'Asia/Shanghai', 2200, 600, 200, 100, 0, 3100, 1.23, 4, 2, 'observed', 'seed', '{"seed":"claude-today"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

-- 两个账号各有一条**同类型、同窗口**的官方观测，只有观测时刻与百分比不同。
INSERT INTO limit_windows (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at,
  first_seen_at, last_seen_at
) VALUES
  ('claude-main', 'claude', 'week', 78.25, 21.75, '2026-06-10T00:00:00+08:00', 10080, 'oauth_usage_api', 'observed', 'ok', '2026-06-03T11:03:00+08:00', '2026-06-03T11:03:00+08:00', '2026-06-03T11:03:00+08:00'),
  ('claude-second', 'claude', 'week', 40.0, 60.0, '2026-06-10T00:00:00+08:00', 10080, 'oauth_usage_api', 'observed', 'ok', '2026-06-03T11:30:00+08:00', '2026-06-03T11:30:00+08:00', '2026-06-03T11:30:00+08:00');
