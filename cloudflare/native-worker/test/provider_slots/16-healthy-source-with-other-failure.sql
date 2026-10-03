-- #228：其他设备的较新失败不遮住本机可信周额度；仍只展示一个来源。
-- owner 重放此 SQL 生成 golden 与客户端 fixture，禁止手工填写 JSON。
INSERT INTO limit_windows (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at,
  first_seen_at, last_seen_at
) VALUES
  ('codex-macmini', 'codex', 'week', 20, 80, '2026-06-10T05:13:05+08:00', 10080,
   'runtime_api', 'observed', 'ok', '2026-06-03T11:00:00+08:00',
   '2026-06-03T11:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('codex-main', 'codex', 'status', 0, 0, '', 0,
   'runtime_api', 'missing', 'provider_failed', '2026-06-03T11:30:00+08:00',
   '2026-06-03T11:30:00+08:00', '2026-06-03T11:30:00+08:00');
