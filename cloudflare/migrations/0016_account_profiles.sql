-- #287：账户资料（展示名 + 套餐）。额度来源 -> 账户的对应关系复用 account_observations。
-- 每个 (账户, 套餐) 一行：first_seen_at / last_seen_at 给出该套餐被观测到的时间段，
-- 同一账户出现第二个套餐即「套餐变化」，变化时刻 = 新套餐行的 first_seen_at。
-- plan 识别不出时写 'unknown'（主键列不用 NULL：SQLite 非 INTEGER 主键允许多个 NULL）。
CREATE TABLE IF NOT EXISTS account_profiles (
  provider TEXT NOT NULL,
  account_fingerprint TEXT NOT NULL,
  plan TEXT NOT NULL,
  label TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (provider, account_fingerprint, plan)
);

-- #287：脏日队列改为登记 UTC 日（原为写死 +8 小时的北京日）。Worker 按 AIUSAGE_TIMEZONE
-- 把每个脏 UTC 日换算成它覆盖的本地日再重算 rollup。只重建触发器，不改表结构。
DROP TRIGGER IF EXISTS usage_rollup_dirty_insert;
DROP TRIGGER IF EXISTS usage_rollup_dirty_delete;
DROP TRIGGER IF EXISTS usage_rollup_dirty_update;
CREATE TRIGGER usage_rollup_dirty_insert
AFTER INSERT ON usage_hourly_facts
BEGIN
  INSERT INTO usage_rollup_dirty_days (date) VALUES (date(NEW.window_start)) ON CONFLICT(date) DO NOTHING;
END;

CREATE TRIGGER usage_rollup_dirty_delete
AFTER DELETE ON usage_hourly_facts
BEGIN
  INSERT INTO usage_rollup_dirty_days (date) VALUES (date(OLD.window_start)) ON CONFLICT(date) DO NOTHING;
END;

CREATE TRIGGER usage_rollup_dirty_update
AFTER UPDATE ON usage_hourly_facts
WHEN OLD.source_id IS NOT NEW.source_id OR OLD.machine_id IS NOT NEW.machine_id
  OR OLD.os_user IS NOT NEW.os_user OR OLD.ai_provider IS NOT NEW.ai_provider
  OR OLD.ai_account_id IS NOT NEW.ai_account_id OR OLD.agent IS NOT NEW.agent
  OR OLD.client IS NOT NEW.client OR OLD.window_start IS NOT NEW.window_start
  OR OLD.window_end IS NOT NEW.window_end OR OLD.attribution_confidence IS NOT NEW.attribution_confidence
  OR OLD.provenance IS NOT NEW.provenance OR OLD.input_tokens IS NOT NEW.input_tokens
  OR OLD.output_tokens IS NOT NEW.output_tokens OR OLD.cache_creation_tokens IS NOT NEW.cache_creation_tokens
  OR OLD.cache_read_tokens IS NOT NEW.cache_read_tokens OR OLD.reasoning_output_tokens IS NOT NEW.reasoning_output_tokens
  OR OLD.total_tokens IS NOT NEW.total_tokens OR OLD.total_cost IS NOT NEW.total_cost
  OR OLD.event_count IS NOT NEW.event_count OR OLD.session_count IS NOT NEW.session_count
BEGIN
  INSERT INTO usage_rollup_dirty_days (date) VALUES (date(OLD.window_start)) ON CONFLICT(date) DO NOTHING;
  INSERT INTO usage_rollup_dirty_days (date) VALUES (date(NEW.window_start)) ON CONFLICT(date) DO NOTHING;
END;
