# Project Map

本文是 AI Agent 进场时的项目地图：先看这里，再按任务进入对应权威文档。目标是减少重复搜索、减少读取历史文档导致的误判。

## 必读入口

| 主题 | 当前权威位置 | 说明 |
| --- | --- | --- |
| Agent 规则 | `AGENTS.md` | 只放最小硬规则和入口。 |
| 当前状态 | `docs/status.md` | 产品和执行状态摘要。 |
| 当前架构 | `docs/architecture/architecture.md` | 架构边界、依赖方向、模块 owner、禁止事项。 |
| 当前数据库 | `docs/architecture/database.md` | SQLite 当前表索引；代码为唯一事实源。 |
| 当前接口 | `docs/architecture/interfaces.md` | HTTP、summary、mobile DTO 当前接口索引。 |
| 任务与进度 | GitHub [Issues](https://github.com/Moshuiwang/aiusage/issues) + [Project #1](https://github.com/users/Moshuiwang/projects/1) | 唯一状态真值。任务包体系已于 2026-08-01 归档，见 `docs/task-packages/README.md`。 |
| 项目命令 | `README.md` | 本地运行、测试、pusher、limits 命令。 |

历史任务包、设计稿和评审记录在 `docs/archive/`，默认不要作为当前事实读取。

## 顶层目录

| 目录 | 当前职责 | 注意 |
| --- | --- | --- |
| `src/ai_usage_widget/` | Python server、collector/pusher、SQLite、snapshot、Web 静态资源。 | 当前业务代码主目录。 |
| `tests/` | Python 单元/契约测试。 | Round 8 不改业务测试。 |
| `mobile/ios` | 当前 iOS Swift Package。 | 真实代码；暂不物理搬迁。 |
| `mobile/ios-xcode` | 当前 iPhone App / Widget Xcode 工程。 | 真实代码；暂不物理搬迁。 |
| `widget/macos`、`widget/macos-xcode` | legacy macOS Widget。 | 历史兼容，不作为后续主线。 |
| `clients/` | 目标客户端目录和部分新客户端落点。 | 本轮只建立索引，不搬旧目录。 |
| `components/` | 跨端或原型组件素材。 | 不承载业务聚合。 |
| `packages/client-contracts/` | 跨端展示数据合同、fixture、验收说明目标区。 | 不保存 token 或生产配置。 |
| `packages/design-tokens/` | 跨端状态色、密度、间距、数字格式等视觉语义。 | 不承载业务聚合。 |
| `config/` | 示例配置和本地配置位置。 | `*.local.json` 不提交。 |
| `data/` | 本地 SQLite、latest、备份等运行数据。 | 不提交。 |
| `docs/` | 当前权威文档和 archive 索引。 | 当前事实优先读权威入口。 |
| `docs/archive/reviews/` | 历史 AI review 记录。 | 根部 `reviews/` 仅是临时工作目录，当前不作为文档入口保留。 |
| `.codex/agents/` | 项目级 agent 配置。 | 已纳入跟踪；`.codex` 其他内容仍忽略。 |

顶层 Obsidian 笔记库 `.obsidian/` 和 `ai-usage-widget/欢迎.md` 已由用户在本地移除，本轮不再作为待办。

`docs/prototypes/*` 当前只保留 symlink 指针，真实原型内容在 `docs/archive/prototypes/`。
这是为了兼容现有原型测试，同时避免默认 `rg` 搜索进入历史原型内容。

## 客户端目录边界

Round 8 不做客户端物理搬迁，只给 AI 明确当前真实代码和目标目录。

| 平台 | 用户体验 | 当前真实代码 | 目标目录 | 本轮动作 |
| --- | --- | --- | --- | --- |
| Web | 完整 dashboard：机器、OS 用户、agent、趋势、source health、可信 limits。 | `src/ai_usage_widget/static` | `clients/web` | 只记录映射，不搬迁。 |
| iPhone / iOS Widget | App 是移动主体验；Widget 是轻量摘要。 | `mobile/ios`、`mobile/ios-xcode` | `clients/ios` | 只记录映射，不搬迁。 |
| Android / Android Widget | 复用移动端主体验和 mobile summary。 | 暂无真实实现 | `clients/android` | 后续独立任务包。 |
| macOS | 菜单栏或轻量桌面入口；打开 dashboard 看完整信息。 | `clients/macos` 有新菜单栏方向；`widget/macos*` 为 legacy。 | `clients/macos` | 不复用 legacy Widget 主线。 |
| Windows | 托盘或轻量桌面入口。 | 暂无真实实现 | `clients/windows` | 后续独立任务包。 |

规则：

- Web dashboard 使用 `/api/summary`。
- iOS、Android、macOS 菜单栏、Windows 托盘优先使用 `/api/mobile/summary` 或由它裁剪的轻量摘要。
- 客户端不直接读取 SQLite。
- 客户端不执行 `ccusage`、SSH 或 provider。
- 客户端不从 daily token 推断官方额度。
- 真正合并 `clients/`、`mobile/`、`widget/` 的物理目录必须另开独立治理轮次或任务包，不并入 Round 8。

## 当前代码 owner

| 模块 | Owner |
| --- | --- |
| `server.py` | HTTP route、认证入口、request/response 适配。 |
| `server_services.py` | HTTP 背后的业务编排。 |
| `ingest.py` | Usage ingest payload 校验和敏感字段边界。 |
| `storage_sqlite.py` | SQLite schema、upsert、WAL/busy timeout。 |
| `snapshot_builder.py` | `/api/summary` read model。 |
| `mobile_summary.py` | `/api/mobile/summary` DTO。 |
| `limits_*` / provider modules | 官方额度 provider、runtime、doctor、scheduler、push。 |
| `pusher.py` | 设备本机采集和 HTTP push。 |

新增字段或接口时，先找 owner，不要在客户端、route handler 或历史文档里重新定义一套口径。
