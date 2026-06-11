# Client Contracts

这里放客户端共享的数据合同说明和 fixture。

当前合同边界：

- Web dashboard 使用 `/api/summary`。
- iPhone / Android / Widget / 轻量桌面入口优先使用 `/api/mobile/summary`。
- 客户端不直接读取 SQLite，也不重新聚合 usage / limits。

后续新增字段顺序：

1. 先在 `snapshot_builder.py` 或 `mobile_summary.py` 固定 read model / DTO。
2. 再补合同 fixture 和测试。
3. 最后改对应客户端 UI。
