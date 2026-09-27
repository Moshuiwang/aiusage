-- Migration 0014: #190 降 D1 rows_read。
--
-- 1) usage_hourly_rollups / usage_daily_rollups 补 total_cost（sum，可为 NULL）。
--    此前 summary 每次请求都为了取 items 的 total_cost 单独对 usage_hourly_facts
--    做一次全期间扫描（read-model/db.ts 的 fetchFactRows），即使 fetchAccountHourlyRows
--    已经从 rollup 读过同一批数据也照样再扫一遍。rollup 补上 total_cost 后，
--    fetchAccountHourlyRows 可以直接从已经读到的行里算出 costsByItem，不再需要
--    这次额外的 facts 扫描（对账户小时行已经在用 rollup 的 week/month/all 请求，
--    这次改动省掉的是整整一次 usage_hourly_facts 全表级联 JOIN 扫描）。
--
--    用表重建而不是 `ALTER TABLE ... ADD COLUMN`：`wrangler d1 migrations apply` 在全新
--    D1 上会依次重放 0001..0014，而 0001 已经直接创建带 total_cost 的两张表（见其
--    "Backfilled from 0014" 注释），裸 ADD COLUMN 会在全新安装路径上炸
--    "duplicate column name"（0007 同款教训）。重建对两条路径都成立：对已经跑到 0013
--    的部署库是真的追加列；对全新库是等价重建。
--    列必须放在最后：SQLite 的 ADD COLUMN 语义只能追加，重建时保持同样的落位，
--    全新安装（0001 CREATE TABLE）与增量安装（这份重建）才不会在列序上分叉。
--
--    生产库已有历史行：INSERT 用 LEFT JOIN 对 usage_hourly_facts 按 handlers.ts::
--    refreshDisplayRollups 同款分组键回填 total_cost，不是留空——留空会让已有历史日期的
--    items[].total_cost 在部署后集体变成 null（这些日期不会再被标脏重算，NULL 会一直
--    留在那里，不是等下一次 ingest 就自己修好），"输出不变" 的承诺对存量数据会直接失效。
--
--    !! 不要在已经有 total_cost 列的库上手工单独跑这个文件 !!
--    这份迁移只在结构上可重复执行，不保值：手工重跑会用当时的 usage_hourly_facts
--    重新回填一遍 total_cost——如果这期间 facts 有被删除/改写，重跑就会覆盖掉之前
--    某次增量重算已经算出的正确值（`wrangler d1 migrations apply` 不会重放已应用过的
--    迁移，所以只有手工重跑才会踩到，等价于 0007 的已知代价）。
--
--    两张表原有的显式索引（idx_usage_hourly_rollups_bucket / idx_usage_daily_rollups_date）
--    随 DROP TABLE 一起消失，下面重建后原样恢复；两张表没有触发器、视图或外键引用它们。
--
-- 2) 三个按 window_start/bucket_start 范围过滤的表达式索引。
--    read-model/db.ts 的 periodWhere 一律写成
--    `julianday(window_start) >= julianday(?) AND julianday(window_start) < julianday(?)`——
--    用 julianday() 是因为 window_start 是带时区偏移的 ISO8601 文本，不同偏移量下直接按
--    字符串比较不保证按时间顺序；但 SQLite 的默认列索引（如已有的
--    idx_usage_hourly_facts_window(window_start, window_end)）只能匹配「列本身」出现在
--    WHERE 里的谓词，一旦列被 julianday() 包住，索引就用不上，退化成全表扫描。
--    这里新增的是「表达式索引」——直接对 julianday(window_start) 建索引，让同一个表达式
--    在 WHERE 里出现时可以走 SEARCH 而不是 SCAN，不改变任何返回值，只新建索引；
--    这三条 DDL 带 IF NOT EXISTS 修饰，在全新安装/增量安装两条路径上都是幂等的。
--    生产索引写入成本：三张表都是仅追加（INSERT-heavy，facts 无 UPDATE window_start，
--    rollups 每次重算是 DELETE+INSERT 同一批 dirty day），新增索引的维护成本随之只发生在
--    这些既有写路径里，不引入新的写放大量级；索引本身体量与主表 window_start/bucket_start
--    列相近（一个 8 字节 rowid 引用 + 索引项），代价远小于反复全表扫描省下的 rows_read。

CREATE TABLE usage_hourly_rollups_v2 (
  bucket_start TEXT NOT NULL, bucket_end TEXT NOT NULL, source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL, os_user TEXT NOT NULL, ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL, agent TEXT NOT NULL, client TEXT NOT NULL,
  attribution_confidence TEXT NOT NULL, provenance TEXT NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
  cache_creation_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL,
  reasoning_output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
  event_count INTEGER NOT NULL, session_count INTEGER NOT NULL, fact_count INTEGER NOT NULL,
  total_cost REAL,
  PRIMARY KEY (bucket_start, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance)
);

-- 按 handlers.ts::refreshDisplayRollups 的 hourly 分组键（bucket_start + 9 个身份列）
-- 对 usage_hourly_facts 求 sum(total_cost)，LEFT JOIN 回填每一行已有的 total_tokens 等
-- 列不动，只补新列。没有匹配 facts 的行（比如历史 fallback provenance 本来就没有
-- facts）保持 NULL，和 handlers.ts 现在算出来的值同口径。
INSERT INTO usage_hourly_rollups_v2 (
  bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
  reasoning_output_tokens, total_tokens, event_count, session_count, fact_count, total_cost
)
SELECT r.bucket_start, r.bucket_end, r.source_id, r.machine_id, r.os_user, r.ai_provider, r.ai_account_id, r.agent, r.client,
       r.attribution_confidence, r.provenance, r.input_tokens, r.output_tokens, r.cache_creation_tokens, r.cache_read_tokens,
       r.reasoning_output_tokens, r.total_tokens, r.event_count, r.session_count, r.fact_count, costs.total_cost
FROM usage_hourly_rollups r
LEFT JOIN (
  SELECT strftime('%Y-%m-%dT%H:00:00', window_start, '+8 hours') || '+08:00' AS bucket_start,
         source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
         attribution_confidence, provenance, sum(total_cost) AS total_cost
  FROM usage_hourly_facts
  GROUP BY bucket_start, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
           attribution_confidence, provenance
) costs
  ON costs.bucket_start = r.bucket_start AND costs.source_id = r.source_id AND costs.machine_id = r.machine_id
  AND costs.os_user = r.os_user AND costs.ai_provider = r.ai_provider AND costs.ai_account_id = r.ai_account_id
  AND costs.agent = r.agent AND costs.client = r.client
  AND costs.attribution_confidence = r.attribution_confidence AND costs.provenance = r.provenance;

DROP TABLE usage_hourly_rollups;
ALTER TABLE usage_hourly_rollups_v2 RENAME TO usage_hourly_rollups;

CREATE INDEX IF NOT EXISTS idx_usage_hourly_rollups_bucket
  ON usage_hourly_rollups(bucket_start);

CREATE TABLE usage_daily_rollups_v2 (
  date TEXT NOT NULL, bucket_start TEXT NOT NULL, bucket_end TEXT NOT NULL, source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL, os_user TEXT NOT NULL, ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL, agent TEXT NOT NULL, client TEXT NOT NULL,
  attribution_confidence TEXT NOT NULL, provenance TEXT NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
  cache_creation_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL,
  reasoning_output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
  event_count INTEGER NOT NULL, session_count INTEGER NOT NULL, fact_count INTEGER NOT NULL,
  total_cost REAL,
  PRIMARY KEY (date, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance)
);

-- 同上，daily 分组键是 date（handlers.ts 用 date(window_start,'+8 hours')）+ 9 个身份列。
INSERT INTO usage_daily_rollups_v2 (
  date, bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
  attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
  reasoning_output_tokens, total_tokens, event_count, session_count, fact_count, total_cost
)
SELECT r.date, r.bucket_start, r.bucket_end, r.source_id, r.machine_id, r.os_user, r.ai_provider, r.ai_account_id, r.agent, r.client,
       r.attribution_confidence, r.provenance, r.input_tokens, r.output_tokens, r.cache_creation_tokens, r.cache_read_tokens,
       r.reasoning_output_tokens, r.total_tokens, r.event_count, r.session_count, r.fact_count, costs.total_cost
FROM usage_daily_rollups r
LEFT JOIN (
  SELECT date(window_start, '+8 hours') AS date,
         source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
         attribution_confidence, provenance, sum(total_cost) AS total_cost
  FROM usage_hourly_facts
  GROUP BY date, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
           attribution_confidence, provenance
) costs
  ON costs.date = r.date AND costs.source_id = r.source_id AND costs.machine_id = r.machine_id
  AND costs.os_user = r.os_user AND costs.ai_provider = r.ai_provider AND costs.ai_account_id = r.ai_account_id
  AND costs.agent = r.agent AND costs.client = r.client
  AND costs.attribution_confidence = r.attribution_confidence AND costs.provenance = r.provenance;

DROP TABLE usage_daily_rollups;
ALTER TABLE usage_daily_rollups_v2 RENAME TO usage_daily_rollups;

CREATE INDEX IF NOT EXISTS idx_usage_daily_rollups_date
  ON usage_daily_rollups(date);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_window_julianday
  ON usage_hourly_facts(julianday(window_start));

CREATE INDEX IF NOT EXISTS idx_usage_hourly_rollups_bucket_julianday
  ON usage_hourly_rollups(julianday(bucket_start));

CREATE INDEX IF NOT EXISTS idx_usage_daily_rollups_bucket_julianday
  ON usage_daily_rollups(julianday(bucket_start));
