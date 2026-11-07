-- #287：多账户 + 套餐变化 + 同一账户被两台机器读到（2026-11-07 实测形态的离线复刻）。
--
-- - Claude「Zhipeng」：tz-wangzp 读到，周已用 82%；套餐 2026-06-01 起由 max_20x 变为 max_5x。
-- - Claude「Tony」：tz-wangzhipeng 读到，周已用 10%，max_20x。
-- - OpenAI「Em」：mac-local 与 tz-wangzp-codex 都读到；TZ 那份较新但失败，取 Mac 的可信读数 55%。
-- - Antigravity：没有账户身份，退回 provider 级格子。
-- - 用量：mac-local 的 claude 用量没有账户观察 → 记入未归属；tz-wangzp 的 claude 用量归 Zhipeng。
-- 固定参考时间 2026-06-03T12:00:00+08:00（Asia/Shanghai），period=today。

INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at) VALUES
  ('mac-local', 'macbook-pro', 'macbook-pro', 'alice', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('tz-wangzp', 'tz', 'tz', 'wangzp', 'linux', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at) VALUES
  ('macbook-pro', 'macbook-pro', 'macbook-pro', 'darwin', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('tz', 'tz', 'tz', 'linux', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO usage_hourly_facts (
  fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
  session_count, attribution_confidence, provenance, metadata_json, first_seen_at, last_seen_at
) VALUES
  ('fact-tz-claude-09', 'tz-wangzp', 'tz', 'wangzp', 'claude', 'unknown', 'claude', 'cli', '2026-06-03T09:00:00+08:00', '2026-06-03T10:00:00+08:00', 'Asia/Shanghai', 2000, 500, 0, 0, 0, 2500, NULL, 3, 1, 'observed', 'seed', NULL, '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('fact-mac-claude-10', 'mac-local', 'macbook-pro', 'alice', 'claude', 'unknown', 'claude', 'cli', '2026-06-03T10:00:00+08:00', '2026-06-03T11:00:00+08:00', 'Asia/Shanghai', 300, 100, 0, 0, 0, 400, NULL, 1, 1, 'observed', 'seed', NULL, '2026-06-03T10:00:00+08:00', '2026-06-03T11:30:00+08:00');

INSERT INTO account_observations (source_id, provider, account_fingerprint, first_seen_at, last_seen_at) VALUES
  ('tz-wangzp', 'claude', 'fp:claude:aaaaaaaaaaaaaaaaaaaaaaaa', '2026-05-01T00:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('tz-wangzhipeng', 'claude', 'fp:claude:bbbbbbbbbbbbbbbbbbbbbbbb', '2026-05-01T00:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('mac-local-codex', 'codex', 'fp:codex:cccccccccccccccccccccccc', '2026-05-01T00:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('tz-wangzp-codex', 'codex', 'fp:codex:cccccccccccccccccccccccc', '2026-05-01T00:00:00+08:00', '2026-06-03T11:00:00+08:00');

INSERT INTO account_profiles (provider, account_fingerprint, plan, label, first_seen_at, last_seen_at) VALUES
  ('claude', 'fp:claude:aaaaaaaaaaaaaaaaaaaaaaaa', 'max_20x', 'Zhipeng', '2026-05-01T00:00:00+08:00', '2026-05-31T00:00:00+08:00'),
  ('claude', 'fp:claude:aaaaaaaaaaaaaaaaaaaaaaaa', 'max_5x', 'Zhipeng', '2026-06-01T00:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('claude', 'fp:claude:bbbbbbbbbbbbbbbbbbbbbbbb', 'max_20x', 'Tony', '2026-05-01T00:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('codex', 'fp:codex:cccccccccccccccccccccccc', 'pro', 'Em', '2026-05-01T00:00:00+08:00', '2026-06-03T11:00:00+08:00');

INSERT INTO limit_windows (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at,
  first_seen_at, last_seen_at
) VALUES
  ('tz-wangzp', 'claude', 'week', 82.0, 18.0, '2026-06-08T02:00:00+08:00', 10080, 'official_cli', 'observed', 'ok', '2026-06-03T11:30:00+08:00', '2026-06-03T11:30:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('tz-wangzhipeng', 'claude', 'week', 10.0, 90.0, '2026-06-09T05:00:00+08:00', 10080, 'official_cli', 'observed', 'ok', '2026-06-03T11:20:00+08:00', '2026-06-03T11:20:00+08:00', '2026-06-03T11:20:00+08:00'),
  ('mac-local-codex', 'codex', 'week', 55.0, 45.0, '2026-06-08T02:56:00+08:00', 10080, 'runtime_api', 'observed', 'ok', '2026-06-03T11:25:00+08:00', '2026-06-03T11:25:00+08:00', '2026-06-03T11:25:00+08:00'),
  ('tz-wangzp-codex', 'codex', 'unknown', 0, 0, '2026-06-03T11:50:00+08:00', 0, 'provider_runtime', 'missing', 'provider_failed', '2026-06-03T11:50:00+08:00', '2026-06-03T11:50:00+08:00', '2026-06-03T11:50:00+08:00'),
  ('antigravity-mac', 'antigravity', 'week', 5.0, 95.0, '2026-06-09T00:00:00+08:00', 10080, 'language_server', 'observed', 'ok', '2026-06-03T11:40:00+08:00', '2026-06-03T11:40:00+08:00', '2026-06-03T11:40:00+08:00');
