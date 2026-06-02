# Limits / Quota Source

## 用途

这份文档定义 limits/quota 数据源方向。它只处理 5h / week quota、reset time、usage percentage、weekly window 这类 `ccusage daily --json` 不能直接提供的信息。

当前工程化方向中，limits 是可插拔能力，不是 baseline pipeline 的前置依赖。

## 背景

baseline 依赖：

```text
ccusage daily --json
```

它适合生成 daily token usage facts，但不能直接提供：

- official quota limit。
- used percentage。
- reset window。
- subscription 级状态。

因此 limits 必须走独立 source，不能混进 daily normalizer，不能由 daily token history 硬推。

## 目标输出

目标 snapshot 字段名使用 `limits`。迁移时如果已有 `quota_windows` 设计，可通过 builder 映射，但展示层最终只依赖 versioned snapshot contract。

```json
{
  "limits": [
    {
      "source_id": "mac-local",
      "agent": "claude-code",
      "window": "5h",
      "used": 1842000,
      "limit": 2500000,
      "used_percentage": 0.7368,
      "resets_at": "2026-05-24T17:00:00+08:00",
      "observed_at": "2026-05-24T12:28:00+08:00",
      "status": "ok",
      "source_type": "structured_export",
      "confidence": "observed"
    }
  ]
}
```

字段规则：

- `window`：`5h`、`week`，后续可扩展。
- `used_percentage`：0 到 1 的数字；估算必须标明 `confidence`。
- `resets_at`：带时区 ISO 8601。
- `observed_at`：该 limit fact 的观测时间。
- `source_type`：`structured_export`、`blocks_estimate`、`manual_config`、`official_api` 等。
- `confidence`：`observed`、`estimated`、`missing`、`unsupported`。
- `status`：`ok`、`stale`、`missing`、`unsupported`、`failed`。

## 核心原则

不要通过本地日志推算官方限额窗口。

本地日志、SQLite 和 session JSONL 只能用于：

- token 历史统计。
- cost 历史统计。
- session / model / machine / account 分析。

官方额度窗口必须优先从官方运行时接口或官方客户端暴露的本地 RPC 获取。原因：

- 官方使用滑动窗口。
- 官方可能动态调整额度。
- 本地 token 历史无法准确推导 reset time。
- 公开项目 CodexBar 已经采用官方 provider 路线，而不是从日志推 reset。

## Official Limits Provider

目标新增独立 provider 层：

```text
Official Limits Provider -> Limit Payload -> HTTP Ingest -> limit_windows -> Snapshot limits
```

统一抽象：

```text
UsageProvider.get_usage() -> UsageInfo
```

目标输出：

```json
{
  "provider": "codex",
  "window": "week",
  "used_percent": 37,
  "remaining_percent": 63,
  "reset_at": "2026-06-08T00:00:00+08:00",
  "window_duration_minutes": 10080,
  "observed_at": "2026-06-01T12:00:00+08:00",
  "source_type": "runtime_api",
  "confidence": "observed",
  "status": "ok"
}
```

字段说明：

- `used_percent` / `remaining_percent`：0 到 100 的百分比数字，不是 0 到 1 的小数。
- `source_type`：官方运行时接口使用 `runtime_api`；CLI 交互读取可用 `cli_usage`；本地历史推导必须标为 `local_history_estimate` 且不能作为 official reset。
- `confidence`：只有 `observed` 可作为官方观测；`estimated`、`missing`、`unsupported` 只能降级展示。
- `status`：`ok`、`missing_credentials`、`unsupported`、`provider_failed` 等。

### Claude Code Provider

优先级：

1. OAuth Usage API。
2. Claude CLI `/usage`，通过 PTY 手动触发并解析。
3. Claude Web API。

首选路径：

```text
~/.claude/.credentials.json
macOS Keychain: Claude Code-credentials
GET https://api.anthropic.com/api/oauth/usage
```

期望窗口：

- 当前 session / 5h window。
- 当前 weekly window。
- used percent。
- reset time。

CLI fallback 只用于官方 CLI 已展示的 `/usage` 内容；不得从 `~/.claude/projects` 日志反推 reset。

### Codex Provider

CodexBar 源码确认的 app 默认优先级：

1. OAuth API：读取 `~/.codex/auth.json`，调用 `GET https://chatgpt.com/backend-api/wham/usage`。
2. CLI RPC：启动 `codex -s read-only -a untrusted app-server`，调用 `account/read` 和 `account/rateLimits/read`。

CodexBar CLI 的 `--source auto` 另有不同默认顺序：

1. OpenAI web dashboard。
2. Codex CLI RPC。

本项目面向长期后台采集，采用 app 默认路线：**OAuth/WHAM 优先，CLI RPC fallback**。原因：

- `wham/usage` 可直接返回 primary / secondary windows 和 reset。
- `account/rateLimits/read` 依赖本机 `codex app-server` 可启动，适合作为本地 fallback。
- OpenAI web dashboard extras 涉及 cookie / WebView / browser profile，默认不进入 MVP。

期望字段：

- `usedPercent` 或等价 percentage。
- `resetsAt` / `reset_at`。
- `windowDurationMins`。
- primary / secondary window。

### Antigravity Provider

后续预留，不进入第一版 MVP。

候选路径：

1. 本地 Language Server `GetUserStatus`。
2. fallback `GetCommandModelConfigs`。

期望字段：

- remaining fraction。
- reset time。
- window metadata。

## 候选通道

### A: 结构化导出缓存

目标：

- 由明确配置的 hook、companion process 或后续官方能力写出小型 JSON。
- collector 只读取该结构化 JSON。

候选路径示例：

```text
~/.claude/active_limits.json
~/.codex/active_limits.json
```

约束：

- 必须确认字段真实存在，再标为 `confidence: "observed"`。
- 写 hook 前必须先备份和审查用户配置。
- 远程读取只允许读取明确配置的结构化文件。
- 文件过期时标为 `stale`。

### B: 本地 block/session fallback

目标：

- 在没有结构化导出时，用 `ccusage blocks --json` 提供辅助视角。

限制：

- `blocks` 是本地 block/session 视角，不是官方 subscription quota。
- 推出的 reset 或 percentage 必须标为 `confidence: "estimated"`。
- UI 不能把 estimated 显示成官方额度。

### C: 官方 API / 本地 RPC / 手动配置

适用：

- Claude / Codex / Antigravity 等 provider 可提供官方额度窗口。
- 用户愿意手动配置 limit。

要求：

- 明确来源。
- 明确刷新频率。
- 明确过期策略。
- 明确是否可用于 observed 语义。
- 官方 provider 失败时必须产生 `failed` 或 `missing` 状态，不得回退到本地 token history 推算 official reset。

## 降级规则

- `observed`：可以展示百分比、reset time 和窗口标签。
- `estimated`：可以展示估算，但必须弱化视觉和文案。
- `stale`：显示上次观测时间，不显示强进度结论。
- `missing` / `unsupported` / `failed`：回退到 daily usage baseline。

## 落地顺序

1. 定义 official limits provider contract 和 fixtures。
2. Codex provider：先实现 OAuth/WHAM fixture parser，再实现 CLI RPC fallback contract。
3. Claude provider：先实现 OAuth usage fixture parser，再做 CLI `/usage` fallback spike。
4. 写入 canonical store 的 `limit_windows`。
5. 由 snapshot builder 输出 `limits`。
6. Web dashboard / Widget 根据 confidence 做展示或降级。
7. Antigravity provider 另开后续 spike，不阻塞 Claude + Codex MVP。
