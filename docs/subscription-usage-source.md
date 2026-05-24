# Limits / Quota Source

## 用途

这份文档定义 limits/quota 数据源方向。它只处理 5h / week quota、reset time、usage percentage 这类 `ccusage daily --json` 不能直接提供的信息。

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

### C: 手动配置或后续官方 API

适用：

- 用户愿意手动配置 limit。
- 后续找到官方 API 或导出能力。

要求：

- 明确来源。
- 明确刷新频率。
- 明确过期策略。
- 明确是否可用于 observed 语义。

## 降级规则

- `observed`：可以展示百分比、reset time 和窗口标签。
- `estimated`：可以展示估算，但必须弱化视觉和文案。
- `stale`：显示上次观测时间，不显示强进度结论。
- `missing` / `unsupported` / `failed`：回退到 daily usage baseline。

## 落地顺序

1. 先完成 baseline pipeline hardening。
2. 定义 limits fixture contract。
3. 实现只读 file adapter。
4. 写入 canonical store。
5. 由 snapshot builder 输出 `limits`。
6. Widget 根据 confidence 做展示或降级。
