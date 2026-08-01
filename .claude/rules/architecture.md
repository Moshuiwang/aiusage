---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python 服务端架构边界

核心数据流是**单向 push 管道**，不要反向依赖：

```
设备本机采集 (pusher.py: ccusage daily/session/blocks + mswusage-codex)
  -> POST /ingest, /ingest-limits    server.py            HTTP 适配，仅路由/认证/请求响应
  -> server_services.py                                   业务编排，不依赖 HTTP 对象
  -> storage_sqlite.py                                    本地 canonical store（生产权威库是 D1）
  -> snapshot_builder.py                                  /api/summary 的唯一 read model owner
  -> mobile_summary.py                                    /api/mobile/summary DTO，只裁剪不重算口径
  -> clients（Web / iOS App+Widget / Watch / macOS 菜单栏）  只读
```

## 模块 owner 边界

新增字段或接口先找 owner，**不要**在 route handler、客户端或文档里重定义口径。

| 关注点 | 唯一权威 |
| --- | --- |
| HTTP 路由 / 认证 / 登录 cookie / 静态文件 | `server.py` |
| ingest / limits ingest / summary / health 编排 | `server_services.py` |
| ingest payload 校验 + 敏感字段边界 | `ingest.py` |
| SQLite schema / upsert / 迁移 | `storage_sqlite.py` |
| Web summary 读模型（period/filter/trend/limits/hourly residual） | `snapshot_builder.py`（+ `snapshot_*.py` helper） |
| Mobile DTO | `mobile_summary.py` |
| 官方额度 provider / runtime / doctor / scheduler / push | `*_limits_provider.py`、`limits_*.py` |

接口与 schema 的唯一权威是上述代码，不是 `docs/architecture/interfaces.md`（索引而已）。

当前 HTTP 接口：`/ingest`、`/ingest-limits`（Bearer）、`/api/summary`、`/api/mobile/summary`、
`/api/health`（Bearer 或 cookie）、`/login`、`/`、`/dashboard`、`/static/*`。
summary 与 mobile 共享查询参数 `date` / `period(today|week|month|all)` / `machine` / `account`。

## 测试约定

- 纯标准库 `unittest`，无 pytest、无网络、无真实 `ccusage`/SSH/provider。
- 新测试必须可离线 fixture 重放。
- 重构必须保持现有 API path、HTTP method、status code 和 JSON 合约不变。
- 无 lint / formatter 配置。CLI 入口 `ai_usage_widget.cli:main`，日常用 `python3 -m ai_usage_widget.cli`。
- `collector.py` / SSH 是 legacy，新功能不得依赖。
