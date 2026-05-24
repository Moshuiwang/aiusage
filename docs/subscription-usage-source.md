# Subscription Usage Source

## 用途

这份文档定义 quota/reset-aware Widget 需要补充的数据源方向。它只处理 5h / week quota、reset time、usage percentage 这类 `ccusage daily --json` 不能直接提供的信息。

展示方案见 `docs/display-options.md`，目标 UI 原型见 `docs/ui-direction/wight-ai-usage/`。

## 背景

当前 baseline 依赖：

```text
ccusage daily --json
```

它适合生成 daily token history，但不能直接提供：

- official quota limit。
- used percentage。
- reset window。
- subscription 级状态。

因此 quota/reset 必须作为独立 source 进入 collector，不能混在 daily normalizer 里硬推断。

## 目标输出

collector 最终应把 quota/reset 聚合进 `latest.json`，建议新增顶层字段：

```json
{
  "quota_windows": [
    {
      "source_id": "mac-local",
      "agent": "claude-code",
      "window": "5h",
      "used": 1842000,
      "limit": 2500000,
      "used_percentage": 0.7368,
      "resets_at": "2026-05-24T17:00:00+08:00",
      "status": "ok",
      "source_type": "structured_export",
      "confidence": "observed"
    }
  ]
}
```

字段规则：

- `window`：`5h`、`week`，后续可扩展。
- `used_percentage`：0 到 1 的数字；如果只有估算，必须标明 `confidence`。
- `resets_at`：带时区 ISO 8601。
- `source_type`：例如 `structured_export`、`blocks_estimate`、`manual_config`。
- `confidence`：`observed`、`estimated`、`missing`。
- `status`：`ok`、`stale`、`missing`、`unsupported`、`failed`。

## 候选通道

### 通道 A：结构化导出缓存

目标：

- 在 Claude Code / Codex 运行时，由明确配置的 hook 或 companion 进程写出小型结构化 JSON。
- collector 只读取这个结构化 JSON，不读取或同步 `.claude`、`.codex` 原始日志目录。

候选路径：

```text
~/.claude/active_limits.json
~/.codex/active_limits.json
```

约束：

- 必须确认上游输入字段真实存在，再把它标为 `confidence: "observed"`。
- 写 hook 前必须先备份和审查用户配置；不要直接修改生产账户文件。
- 远程读取只允许读取该结构化导出文件，不允许递归读取 home 目录。
- 文件过期时标为 `stale`，Widget 降级显示。

### 通道 B：本地 block/session fallback

目标：

- 在没有结构化导出时，用 `ccusage blocks --json` 提供辅助视角。

限制：

- `blocks` 是本地 block/session 视角，不是官方 subscription quota。
- 由 block 推出的 reset time 或 percentage 必须标为 `confidence: "estimated"`。
- UI 文案不能把估算说成官方额度。

适用：

- 临时展示“当前活跃窗口可能到什么时候结束”。
- 辅助判断近期 token 结构。
- 不能替代官方 quota source。

### 通道 C：手动配置或后续 API

如果后续找到官方 API、可导出的 subscription 状态，或用户愿意手动配置 quota limit，可以新增 source 类型。

要求：

- 明确来源。
- 明确刷新频率。
- 明确过期策略。
- 明确是否可用于官方语义展示。

## Widget 降级规则

- `observed`：可以展示百分比、reset time 和窗口标签。
- `estimated`：可以展示估算，但必须弱化视觉和文案。
- `stale`：显示上次观测时间，不显示强进度结论。
- `missing` / `unsupported` / `failed`：回退到 daily usage baseline。

## 下一步验证

1. 确认 Claude Code / Codex 是否能通过 hook 或状态输入拿到 quota/reset 字段。
2. 设计 `active_limits.json` 的最小 fixture。
3. 在 Mac 本机先实现只读 file source。
4. 再考虑 SSH 读取远程结构化导出文件。
5. 更新 `docs/architecture.md` 的 `latest.json` schema。
6. 更新 Widget 视图：有 quota window 时显示目标 UI，无数据时显示 baseline。

