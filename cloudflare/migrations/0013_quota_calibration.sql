-- Migration 0013: #183-b 官方额度持续校准的存储层——只新建表，不改任何旧表。
--
-- account_observations：ingest 时 upsert 的账户指纹观察记录，v1 账户口径是「每个 provider
-- 一个账户」，这张表只用来发现冲突（同一 provider 观察到 >1 个指纹），不用来拆分账户。
--
-- quota_calibration：每日 cron 覆盖写的系数结果（cloudflare/native-worker/src/calibration/
-- 计算内核的输出），summary 读它给 breakdown 里的模型行挂 quota_estimate。

CREATE TABLE IF NOT EXISTS account_observations (
  source_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  account_fingerprint TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (source_id, provider, account_fingerprint)
);

CREATE TABLE IF NOT EXISTS quota_calibration (
  provider TEXT NOT NULL,
  model_family TEXT NOT NULL,
  coef REAL NOT NULL,
  effective_delta_u REAL NOT NULL,
  backtest_max_err REAL,
  grade TEXT NOT NULL,
  sample_intervals INTEGER NOT NULL,
  fitted_at TEXT NOT NULL,
  formula_version TEXT NOT NULL,
  PRIMARY KEY (provider, model_family)
);

-- 每日 cron（quota-calibration-cron.ts）按 `WHERE provider = ? AND window = ? AND
-- observed_at >= ?` 读 28 天窗口。已有的 idx_limit_window_history_lookup 领头列是
-- source_id，这条查询没有 source_id，用不上那个索引，会退化成全表扫描。新增一个
-- 领头列是 provider 的索引，避免这条新查询每天全表扫一遍 limit_window_history。
CREATE INDEX IF NOT EXISTS idx_limit_window_history_provider
  ON limit_window_history (provider, window, observed_at DESC);
