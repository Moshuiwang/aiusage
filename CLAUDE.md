# CLAUDE.md

@AGENTS.md

> 以上是全部硬规则（与 Codex 共用）。本文件只补充 Claude Code 特有机制。

- `.claude/rules/`：分领域细则按改动路径自动加载，不必主动读。
- `/verify`：验证入口与证据等级判定，声称任何任务完成前调用它。
- `/tdd-task`：开发任务执行规则（原子性、先红后绿、subagent 纪律、收口交付）。
- `reviewer` subagent：实现完成后收口前，用它在干净上下文审一遍 diff。
- 硬门禁（不是建议）：Stop hook 拦「改 `src/`、`tests/`、`cloudflare/` 没交代绿测试」和残留
  `wrangler dev` 进程；Bash hook 拦 `pkill -f`、pgrep 等待循环、裸 `gh pr merge`。被拦按提示改。
- 拿到 subagent 报告后立刻 TaskStop；等长任务用 `run_in_background`，不手写 sleep 轮询。
- `.agents/skills/*`、`.codex/agents/*` 只对 Codex 生效，两边不自动同步。
