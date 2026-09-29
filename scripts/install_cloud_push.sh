#!/usr/bin/env bash
# Claude Code 云端环境 setup script 用：安装本包，并把 Stop hook 幂等写入 ~/.claude/settings.json。
# 可重复执行；已有的其它 hook 与设置项保留。任何一步失败都不阻断云端环境启动（始终退出 0）。
#
# 安装源：
#   AI_USAGE_PACKAGE_SPEC   pip 可识别的包规格，优先级最高（如 "git+https://<可访问的仓库地址>@<tag>"）
#   否则若本脚本位于仓库 checkout 内，装 checkout 本身
#   否则（其他仓库的会话，无 checkout）从公开仓库装：
#     git+https://github.com/Moshuiwang/aiusage@${AI_USAGE_PACKAGE_REF:-main}
# 需要在云端环境里另行配置两个环境变量（只写名字，值不进仓库）：
#   AI_USAGE_INGEST_TOKEN   ingest Bearer token
#   AI_USAGE_INGEST_URL     完整 ingest 地址（含 /ingest 路径）
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
SPEC="${AI_USAGE_PACKAGE_SPEC:-}"
if [ -z "$SPEC" ] && [ -f "$REPO_ROOT/pyproject.toml" ]; then
  SPEC="$REPO_ROOT"
fi
if [ -z "$SPEC" ]; then
  SPEC="git+https://github.com/Moshuiwang/aiusage@${AI_USAGE_PACKAGE_REF:-main}"
fi

python3 -m pip install --quiet --user "$SPEC" >&2 || { echo "install_cloud_push: pip install 失败，跳过" >&2; exit 0; }
BIN="$(python3 -c 'import sysconfig;print(sysconfig.get_path("scripts","posix_user"))' 2>/dev/null)"
PATH="$BIN:$PATH" ai-usage-widget cloud-push --install-hook >&2 || echo "install_cloud_push: 写入 hook 失败" >&2
exit 0
