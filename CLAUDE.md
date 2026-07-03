# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本仓库以中文协作（`AGENTS.md` 规定「说中文」）。

## 最高优先级：先读规则，再动手

- `AGENTS.md` 是每次会话的最小硬规则和文档路由，**优先级高于本文件**。开发任务必须先读 `docs/task-packages/README.md`，再读 `docs/task-packages/v2/INDEX.md` 和具体任务包。
- **所有开发任务遵守 TDD：先写失败测试，再实现最小代码。** 重构必须保持现有 API path、HTTP method、status code 和 JSON 合约不变。
- **没有用户明确要求，不得 `git add` / `git commit`。** 当前在 `main` 分支上工作。
- 架构治理任务走分轮流程：只执行 `docs/architecture/governance-state.md` 标记的 `next_round`，每轮 baseline→explorer→implement→reviewer→tests→report→stop gate，没有用户确认不得进入下一轮。
- **代码和测试是唯一事实源。** 文档（含架构文档、README、本文件）可能滞后；如与代码冲突，以代码和测试为准并在报告里说明。

## 常用命令

```bash
# 全量测试（stdlib unittest，注意 PYTHONPATH=src 必须带）
PYTHONPATH=src python3 -m unittest discover -s tests -v

# 单个测试文件 / 单个用例
PYTHONPATH=src python3 -m unittest tests.test_mobile_summary -v
PYTHONPATH=src python3 -m unittest tests.test_mobile_summary.TestClassName.test_method

# 终端侧采集并 push（V2 主线）
PYTHONPATH=src python3 -m ai_usage_widget.cli push --config config/sources.local.json --lock-file /tmp/ai-usage-pusher.lock

# 官方额度采集：dry-run / 只校验配置 / 本机 readiness 诊断（不写库、不读 auth 内容）
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits --limits-config config/limits.local.json --dry-run
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits --limits-config config/limits.local.json --check-config
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits --limits-config config/limits.local.json --doctor

# Cloudflare Worker（应用侧本地/部署；真实生产部署与切流走运维，见下）
npm run cf:worker:dev      # wrangler dev --local
npm run cf:worker:deploy   # wrangler deploy
```

- 没有 lint / formatter 配置；CLI 入口是 `ai_usage_widget.cli:main`（`pyproject.toml`），但日常用 `python3 -m ai_usage_widget.cli`。
- 测试是纯标准库 `unittest`，无 pytest 依赖、无网络、无真实 `ccusage`/SSH/provider；新测试也必须可离线 fixture 重放。
- 完整的 collect / backup / limits 各 provider 显式命令见 `README.md`「常用命令」，不在此重复。

## 架构大图（要点，细节见 docs/architecture/）

核心数据流是单向的 push 管道，不要反向依赖：

```
设备本机采集 (pusher.py: ccusage daily/session/blocks + mswusage-codex)
  -> POST /ingest, /ingest-limits        (server.py = HTTP 适配，仅路由/认证/请求响应)
  -> server_services.py                  (业务编排，不依赖 HTTP 对象)
  -> storage_sqlite.py                   (SQLite = canonical store，唯一权威库)
  -> snapshot_builder.py                 (/api/summary 的唯一 read model owner)
  -> mobile_summary.py                   (/api/mobile/summary DTO，只裁剪不重算口径)
  -> clients (Web dashboard / iOS App+Widget / Watch / macOS 菜单栏)  只读
```

模块 owner 边界（新增字段/接口先找 owner，别在 route handler、客户端或文档里重定义口径）：

| 关注点 | 唯一权威 |
| --- | --- |
| HTTP 路由 / 认证 / 登录 cookie / 静态文件 | `server.py` |
| ingest / limits ingest / summary / health 编排 | `server_services.py` |
| ingest payload 校验 + 敏感字段边界 | `ingest.py` |
| SQLite schema / upsert / 迁移 | `storage_sqlite.py` |
| Web summary 读模型（period/filter/trend/limits/hourly residual） | `snapshot_builder.py`（+ `snapshot_*.py` 内部 helper） |
| Mobile DTO | `mobile_summary.py` |
| 官方额度 provider / runtime / doctor / scheduler / push | `*_limits_provider.py`, `limits_*.py` |

接口与 schema 的唯一权威是上述代码，不是 `docs/architecture/interfaces.md`（索引而已）。当前 HTTP 接口：`/ingest`、`/ingest-limits`（Bearer）、`/api/summary`、`/api/mobile/summary`、`/api/health`（Bearer 或 cookie）、`/login`、`/`、`/dashboard`、`/static/*`。summary/mobile 共享查询参数 `date/period(today|week|month|all)/machine/account`。

## 关键不变量（违反会破坏产品可信度）

- **采集只在本机 OS 用户上下文运行**：每个 OS 用户只跑自己的 `ccusage`；`wang` 不读 `/home/ubuntu`；Mac 不读远程 `~/.claude`/`~/.codex` 原始日志。汇聚端**不**通过 SSH 拉取，只接受设备 push 的结构化 payload（`collector.py` / SSH 是 legacy，新功能不得依赖）。
- **官方额度可信度**：只有 `official == true && confidence == "observed" && status == "ok"` 才能当可信官方额度展示。`ccusage daily`/`blocks` 即使带 observed 字段也只是本地估算，禁止伪装成官方 quota。`estimated`/`missing`/`unsupported` 必须降级展示。
- **展示层只读**：客户端不执行 `ccusage`/SSH/provider，不直接读 SQLite 私表重算口径，不在平台侧重新聚合 usage/limits/source health。
- **daily token baseline 优先**：先保护它，limits/quota 只是可插拔 source。
- **不提交**：`data/`、`*.sqlite`、`latest.json`、`config/*.local.json`、token、原始 usage 日志、构建产物（`.gitignore` 已覆盖）。

## Cloudflare 入口与运维边界

- 生产入口是 `https://aiusage.chunbai.com`，由 `cloudflare/aiusage-api-worker.js` 这个 **反向代理 Worker** 回源 `https://vpn2.chunbai.com:8443`（真实 Python 后端）。`wrangler.toml` 已声明 D1/KV/R2 绑定但 Worker 代码尚未使用。
- 最终方向是 **Worker Native**（D1 作权威库，不再回源 VPN2），规划见 `docs/architecture/cloudflare-worker-native-migration-plan.md`。
- **真实 Cloudflare 账号操作（部署、设 Secrets、改路由、线上 smoke）走兄弟目录运维 Agent**：`codex exec --cd /Users/wangzhipeng/Documents/cloud-flare "<任务>"`，凭据在该目录 `.env`，**不读、不输出**。流程见 `cloudflare/OPERATIONS_HANDOFF.md`。
- Worker smoke 用 `GET`（`curl -D - -o /dev/null`），不要用 `HEAD`/`curl -I`；未登录 `/static/*` 返回 401 是预期（origin 把静态资源放在登录态后）。

## 客户端目录现状（迁移期，勿擅自搬）

真实代码暂留原位：iOS 在 `mobile/ios` 与 `mobile/ios-xcode`；Web 静态资源在 `src/ai_usage_widget/static`；legacy macOS Widget 在 `widget/macos*`（仅历史兼容，非后续主线）。`clients/`、`packages/` 是目标落点和跨端合同/设计 token 区。物理搬迁 iOS/Web 文件必须单独开任务包并先补构建/路由验证。

## 仓库身份

GitLab remote 是 `https://gitlab.com/wangzhipeng2010/ai-usage.git`，默认 GitLab 身份 `wangzhipeng2010`。旧 GitHub 仓库 `https://github.com/Moshuiwang/aiusage.git` 不再作为开发、同步或发布入口；如需处理旧仓库，只做迁移提示或归档，不要恢复为默认 remote。
