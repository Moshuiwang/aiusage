-- #74：删除 usage_blocks 表。
--
-- #91（2026-08-03）已停采 `ccusage blocks`：采集端不再发送 `ccusage_blocks_report`，
-- 两侧把它当未知顶层字段忽略（跨实现探针 legacy_collector_payload_ccusage_blocks_report.json
-- 守住老采集端兼容）。Worker 写模型从未写入该表，读模型从未查询它（#90 实测并删除了
-- 不可达的 block 聚合死代码）。表里只剩历史归档数据，无任何消费者。
--
-- IF EXISTS 的原因：0001 已同步移除建表（fresh-install 路径不再创建它），
-- 全新安装重放迁移链时该表不存在；只有先于本迁移部署的 D1 上它才真实存在。
DROP TABLE IF EXISTS usage_blocks;
