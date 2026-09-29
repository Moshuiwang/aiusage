#!/usr/bin/env bash
# 在本机（macOS）找 aiusage 上报 token（AI_USAGE_INGEST_TOKEN），用于填写云端环境变量（#207）。
# 默认：显示来源文件 + 掩码，并把第一个 token 复制到剪贴板；加 --show 显示完整值。
# 只读本机文件，不联网、不写任何文件。
set -uo pipefail
SHOW=0; [ "${1:-}" = "--show" ] && SHOW=1

candidates=("$HOME/Library/Application Support/ai-usage-widget/limits-push.env")
for plist in "$HOME"/Library/LaunchAgents/*.plist; do
  [ -f "$plist" ] || continue
  f=$(plutil -extract EnvironmentVariables.AI_USAGE_ENV_FILE raw -o - "$plist" 2>/dev/null) && candidates+=("$f")
done

found=0; first=""
for f in "${candidates[@]}"; do
  [ -r "$f" ] || continue
  line=$(grep -E '^(export +)?AI_USAGE_INGEST_TOKEN=' "$f" | tail -1) || continue
  tok=${line#*=}; tok=${tok#\'}; tok=${tok%\'}; tok=${tok#\"}; tok=${tok%\"}
  [ -n "$tok" ] || continue
  found=1; [ -z "$first" ] && first=$tok
  echo "$f"
  if [ $SHOW = 1 ]; then echo "  $tok"; else echo "  ${tok:0:4}…${tok: -4}  (长度 ${#tok})"; fi
done

if [ $found = 0 ]; then
  echo "没找到 AI_USAGE_INGEST_TOKEN。可查看 ~/Library/LaunchAgents/ 下 aiusage 相关 plist 的 AI_USAGE_ENV_FILE。" >&2
  exit 1
fi
if [ $SHOW = 0 ]; then printf '%s' "$first" | pbcopy && echo "已复制第一个 token 到剪贴板。"; fi
