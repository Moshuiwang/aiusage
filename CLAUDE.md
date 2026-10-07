# CLAUDE.md

@AGENTS.md

Claude Code 特有：

- `reviewer` subagent：实现完成后、提交前，用它在干净上下文审一遍 diff。
- `/verify`：验证入口与证据等级。
- Bash hook（`scripts/bash_guard.sh`）拦截 `pkill -f`、pgrep 等待循环和裸 `gh pr merge`；被拦按提示改。
