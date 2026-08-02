# CLAUDE.md

@AGENTS.md

> 以上是全部硬规则（与 Codex 共用）。本文件只补充 Claude Code 特有的机制。

## 本仓库的 Claude Code 配置

- `.claude/rules/`：分领域细则，按改动的文件路径**自动加载**（改 `src/**` 加载架构边界，
  改 `cloudflare/**` 加载 CF 运维边界，改客户端目录加载迁移期规则）。不必主动读。
- `/verify`：验证入口与证据等级判定。**声称任何任务完成前调用它。**
- `/tdd-task`：开发任务的执行规则（原子性、先红后绿、收口交付要求）。
- `reviewer` subagent：实现完成后收口前，用它在干净上下文审一遍 diff。
- Stop hook：改动 `src/` 或 `tests/` 却没跑绿测试时会阻止收口；发现残留 `wrangler dev`
  进程也会阻止（`git status` 干净不等于收口干净）。这是硬门禁不是建议。
- Bash hook（`scripts/bash_guard.sh`）：`pkill -f` 与 `until/while + pgrep` 等待循环会被
  直接拦下并给出替代手法——这两个坑在 #68 里各踩过 3 次以上。
- 后台纪律：拿到 subagent 报告后立刻停掉它（TaskStop），「拿到结果」≠「它停了」；
  等长任务用 `run_in_background`（完成会自动唤醒），不手写 sleep 轮询。

## 不加载的目录

`.agents/skills/*` 和 `.codex/agents/*` 只对 Codex 生效，Claude Code 不加载；
两边不自动同步，改一边不等于改了另一边。
