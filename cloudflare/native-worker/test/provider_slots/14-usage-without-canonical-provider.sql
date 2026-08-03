-- #90 缺口块 11：有用量、但**没有 canonical provider**。
--
-- 前 13 个场景里 `unattributed_tokens` 恒为 0，守恒等式
-- `槽位之和 + other_provider_tokens + unattributed_tokens == total_tokens`
-- 的最后一项从未被激活——「完全无法归属的用量」这半边等于没有断言。
-- 而这正是最难发现的一类错：token 既进不了槽位、也没被点名，于是**静默消失**，
-- 用户看到的是「槽位加起来对不上标题总量，DTO 却说一切正常」。
--
-- 本场景：claude 有正常用量（进槽位），另有一段采集到了用量但归属不出 provider
-- 的事实（`ai_provider` 为空、agent 为 unknown、没有对应的 ai_accounts 行）。
-- 期望：那 800 token 必须落进 `unattributed_tokens`，coverage 判 partial。
-- 固定参考时间 2026-06-03T12:00:00+08:00（Asia/Shanghai），period=today。

INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at) VALUES
  ('mac-local', 'macbook-pro', 'macbook-pro', 'alice', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev-bob', 'linux-dev', 'linux-dev', 'bob', 'linux', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');

INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'macbook-pro', 'macbook-pro', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev', 'linux-dev', 'linux-dev', 'linux', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');

INSERT INTO os_identities (machine_id, os_user, display_name, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'alice', 'macbook-pro · alice', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('linux-dev', 'bob', 'linux-dev · bob', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');

-- 刻意只登记 claude：那段无归属用量没有任何 ai_accounts 行可挂。
INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at) VALUES
  ('claude', 'claude-main', 'Claude Team', 'Claude Team', 'pro', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO usage_hourly_facts (
  fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
  session_count, attribution_confidence, provenance, metadata_json, first_seen_at, last_seen_at
) VALUES
  ('fact-claude-20260603-09', 'mac-local', 'macbook-pro', 'alice', 'claude', 'claude-main', 'claude', 'cli', '2026-06-03T09:00:00+08:00', '2026-06-03T10:00:00+08:00', 'Asia/Shanghai', 2200, 600, 200, 100, 0, 3100, 1.23, 4, 2, 'observed', 'seed', '{"seed":"claude-today"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  -- 采集到了用量，但归属不出 provider：ai_provider 为空、agent 为 unknown、无账号。
  ('fact-unattributed-20260603-10', 'linux-dev-bob', 'linux-dev', 'bob', '', '', 'unknown', 'cli', '2026-06-03T10:00:00+08:00', '2026-06-03T11:00:00+08:00', 'Asia/Shanghai', 500, 250, 50, 0, 0, 800, 0.30, 2, 1, 'unconfirmed_local_source', 'seed', '{"seed":"unattributed-today"}', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00');

INSERT INTO limit_windows (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at,
  first_seen_at, last_seen_at
) VALUES
  ('claude-main', 'claude', 'week', 78.25, 21.75, '2026-06-10T00:00:00+08:00', 10080, 'oauth_usage_api', 'observed', 'ok', '2026-06-03T11:03:00+08:00', '2026-06-03T11:03:00+08:00', '2026-06-03T11:03:00+08:00');
