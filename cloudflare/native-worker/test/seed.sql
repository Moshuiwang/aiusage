-- collector_version 必须是**真实设备能写进来的值**：ingest 侧用 semver 白名单校验，
-- 非 semver 的占位串会被 400 拒掉，永远不可能落库。四行分别铺开版本读模型的四种判定，
-- 让跨实现 parity 覆盖多条分支，而不是清一色一种状态
-- （策略常量见 version_contract.py / version-contract.ts：min=0.1.0，target=0.3.0）：
--   run 1 → 0.3.0 → current（等于 target）
--   run 2 → 0.2.0 → update_available（低于 target，仍受支持）
--   run 3 → 0.0.9 → unsupported（低于 min：设备停在旧版本，服务端事后抬高了最低支持线，
--            存量行留在库里，它的下一次上报才会被 400 拒绝）
--   run 4 → NULL  → unknown（0007 迁移后全部存量行都是 NULL，直到设备下次上报，
--            「上线首日全量 unknown」是真实的生产常态）
-- 第五态 rollback_available 需要版本高于 target 或 last_upgrade 失败，四个来源装不下，
-- 由 version_read_surface.test.ts 单边覆盖；不为了凑状态新增 seed 来源。
INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status) VALUES
  (1, '2026-06-03T11:30:00+08:00', 'Asia/Shanghai', '0.3.0', 'ok'),
  (2, '2026-06-03T11:31:00+08:00', 'Asia/Shanghai', '0.2.0', 'ok'),
  (3, '2026-06-03T10:00:00+08:00', 'Asia/Shanghai', '0.0.9', 'partial'),
  (4, '2026-06-03T08:30:00+08:00', 'Asia/Shanghai', NULL, 'ok');

INSERT INTO source_reports (
  id, run_id, source_id, report_type, command, status, ccusage_version,
  first_period, last_period, error_type, error_message
) VALUES
  (1, 1, 'mac-local', 'daily', 'seed.sql', 'ok', NULL, '2026-05-29', '2026-06-03', NULL, NULL),
  (2, 2, 'linux-dev-bob', 'daily', 'seed.sql', 'ok', NULL, '2026-05-15', '2026-06-03', NULL, NULL),
  (3, 3, 'workstation-cara', 'daily', 'seed.sql', 'failed', NULL, '2026-06-01', '2026-06-01', 'provider_failed', 'Antigravity provider unavailable'),
  (4, 4, 'mac-mini-dan', 'daily', 'seed.sql', 'ok', NULL, '2026-04-10', '2026-04-10', NULL, NULL);

-- collector_version 跟着「该来源最新一次报告」所属的 collection_run 一起物化：
-- 它记录的是最后一次被服务端成功接收的采集端版本。
--
-- 注意两侧选「最新报告」的规则并不相同：Python 读模型用
-- `r.id IN (SELECT max(id) FROM source_reports GROUP BY source_id)`（snapshot_builder.py），
-- 这里用 `ROW_NUMBER() OVER (PARTITION BY r.source_id ORDER BY c.collected_at DESC, r.id DESC)`。
-- 本 fixture 每个 source 恰好只有一条报告，两种定义必然重合，所以现在对得上——
-- 这是「恰好重合」，不是「口径一致」。将来给某个 source 加第二条报告、且 collected_at
-- 与 id 的顺序不一致时，必须重新确认两侧选到的是同一行（好在届时 parity 会红，不是静默）。
INSERT INTO source_report_states (
  source_id, collected_at, report_type, command, status, ccusage_version,
  first_period, last_period, error_type, error_message, collector_version
)
SELECT source_id, collected_at, report_type, command, status, ccusage_version,
       first_period, last_period, error_type, error_message, collector_version
FROM (
  SELECT
    r.source_id, c.collected_at, r.report_type, r.command, r.status,
    r.ccusage_version, r.first_period, r.last_period, r.error_type, r.error_message,
    c.collector_version,
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

INSERT INTO usage_hourly_models (
  fact_id, model, input_tokens, output_tokens, cache_creation_tokens,
  cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost,
  metadata_json, first_seen_at, last_seen_at
) VALUES
  ('fact-mac-20260603-09', 'claude-sonnet', 1600, 400, 100, 50, 0, 2150, 0.86, '{"seed":"claude-sonnet"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('fact-mac-20260603-09', 'claude-opus', 600, 200, 100, 50, 0, 950, 0.37, '{"seed":"claude-opus"}', '2026-06-03T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('fact-linux-20260603-10', 'gpt-5', 1000, 500, 100, 0, 25, 1600, 0.72, '{"seed":"gpt-5-today"}', '2026-06-03T10:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('fact-workstation-20260601-10', 'ag-coder', 700, 300, 50, 50, 0, 1100, 0.44, '{"seed":"ag-coder"}', '2026-06-01T10:00:00+08:00', '2026-06-03T10:00:00+08:00'),
  ('fact-mac-20260529-09', 'claude-sonnet', 1200, 500, 300, 0, 0, 2000, 0.84, '{"seed":"claude-sonnet-week"}', '2026-05-29T09:00:00+08:00', '2026-06-03T11:30:00+08:00'),
  ('fact-linux-20260515-12', 'gpt-5', 1600, 900, 500, 0, 40, 3000, 1.50, '{"seed":"gpt-5-month"}', '2026-05-15T12:00:00+08:00', '2026-06-03T11:31:00+08:00'),
  ('fact-mini-20260410-12', 'gpt-4.1', 800, 400, 100, 0, 15, 1300, 0.61, '{"seed":"gpt-4.1-all"}', '2026-04-10T12:00:00+08:00', '2026-06-03T11:32:00+08:00');

INSERT INTO limit_windows (
  source_id, provider, window, used_percent, remaining_percent, reset_at,
  window_duration_minutes, source_type, confidence, status, observed_at,
  first_seen_at, last_seen_at
) VALUES
  ('codex-main', 'codex', '5h', 42.5, 57.5, '2026-06-03T16:00:00+08:00', 300, 'runtime_api', 'observed', 'ok', '2026-06-03T11:00:00+08:00', '2026-06-03T11:00:00+08:00', '2026-06-03T11:00:00+08:00'),
  ('codex-main', 'codex', 'week', 64.25, 35.75, '2026-06-10T00:00:00+08:00', 10080, 'runtime_api', 'observed', 'ok', '2026-06-03T11:01:00+08:00', '2026-06-03T11:01:00+08:00', '2026-06-03T11:01:00+08:00'),
  ('claude-main', 'claude', '5h', 0, 0, '2026-06-03T15:00:00+08:00', 300, 'oauth_usage_api', 'missing', 'provider_failed', '2026-06-03T11:02:00+08:00', '2026-06-03T11:02:00+08:00', '2026-06-03T11:02:00+08:00'),
  ('claude-main', 'claude', 'week', 78.25, 21.75, '2026-06-10T00:00:00+08:00', 10080, 'oauth_usage_api', 'observed', 'ok', '2026-06-03T11:03:00+08:00', '2026-06-03T11:03:00+08:00', '2026-06-03T11:03:00+08:00');
