# CLAUDE.md

@AGENTS.md

> 以上是全部硬规则（与 Codex 共用）。本文件只补充 Claude Code 特有的机制。

## 本仓库的 Claude Code 配置

- `.claude/rules/`：分领域细则，按改动的文件路径**自动加载**（改 `src/**` 加载架构边界，
  改 `cloudflare/**` 加载 CF 运维边界，改客户端目录加载迁移期规则）。不必主动读。
- `/verify`：验证入口与证据等级判定。**声称任何任务完成前调用它。**
- `/tdd-task`：开发任务的执行规则（原子性、先红后绿、收口交付要求）。
- `reviewer` subagent：实现完成后收口前，用它在干净上下文审一遍 diff。
- Stop hook：改动 `src/` 或 `tests/` 却没跑绿测试时会阻止收口，这是硬门禁不是建议。

## 不加载的目录

`.agents/skills/*` 和 `.codex/agents/*` 只对 Codex 生效，Claude Code 不加载；
两边不自动同步，改一边不等于改了另一边。
