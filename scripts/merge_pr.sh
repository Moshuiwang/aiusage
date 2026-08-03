#!/usr/bin/env bash
# PR 合并唯一入口：四个必需 CI check 全部 SUCCESS 才执行合并。
#
# 背景（PM 2026-08-03 决策 A 方案）：免费私有仓库没有服务端 branch protection
# （GitHub 403：需 Pro 或转公开），「全量交给 PR CI」的强制性改由仓库内机制承担：
#   - 本脚本：核对四个必需 check 后才调 `gh pr merge`
#   - scripts/bash_guard.sh：拦截 Bash 工具里的裸 `gh pr merge`，指回这里
# 真需要紧急绕过（CI 基础设施本身挂了）由 PM 在 GitHub 网页端亲自操作，不给脚本留后门。
#
# 用法：scripts/merge_pr.sh <PR号> [gh pr merge 的附加参数，如 --merge --delete-branch]
# 退出码：0 = 门禁通过并已执行合并；2 = 拒绝（条件未满足或用法错误）。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

# 必需 check 清单与 CI 四个 job 同名。改 CI job 名时必须同步这里，
# 否则「缺席不等于通过」的判定会把所有合并拒掉——失效方向是拒绝，不是放行。
REQUIRED_CHECKS="Python
Cloudflare Worker
iOS Swift
macOS Swift"

if [ $# -lt 1 ]; then
  echo "用法: scripts/merge_pr.sh <PR号> [--merge|--squash|--rebase 等 gh pr merge 参数]" >&2
  exit 2
fi
PR="$1"
shift

for arg in "$@"; do
  case "$arg" in
    --admin)
      echo "【merge 门禁】--admin 会绕过 check 判定，禁止。紧急情况由 PM 在 GitHub 网页端操作。" >&2
      exit 2
      ;;
  esac
done

# 测试注入点：给定一份固定的 rollup 快照（name<TAB>状态），让判定可以离线回归。
rollup_snapshot() {
  if [ -n "${AIUSAGE_MERGE_GATE_ROLLUP:-}" ] && [ -r "${AIUSAGE_MERGE_GATE_ROLLUP}" ]; then
    cat "$AIUSAGE_MERGE_GATE_ROLLUP"
  else
    gh pr view "$PR" --json statusCheckRollup \
      --jq '.statusCheckRollup[] | [.name, (.conclusion // .state // "")] | @tsv'
  fi
}

if ! SNAPSHOT="$(rollup_snapshot)"; then
  echo "【merge 门禁】读取 PR #$PR 的 check 状态失败，拒绝合并（读不到不等于绿）。" >&2
  exit 2
fi

FAILED=0
CHECKED=0
while IFS= read -r required; do
  [ -z "$required" ] && continue
  status="$(printf '%s\n' "$SNAPSHOT" | awk -F'\t' -v want="$required" '$1 == want { print $2; exit }')"
  if [ -z "$status" ]; then
    echo "【merge 门禁】必需 check「$required」在 PR #$PR 上不存在——缺席不等于通过（checks 可能尚未注册）。" >&2
    FAILED=1
  elif [ "$status" != "SUCCESS" ]; then
    echo "【merge 门禁】必需 check「$required」状态是 $status，不是 SUCCESS。" >&2
    FAILED=1
  else
    CHECKED=$((CHECKED + 1))
  fi
done <<EOF
$REQUIRED_CHECKS
EOF

# 结构下限：核对数必须正好是 4。REQUIRED_CHECKS 被清空时这里是 0/4，
# 「什么都没核对」不许和「核对了且全绿」产生同一个出口。
if [ "$CHECKED" -ne 4 ] || [ "$FAILED" -ne 0 ]; then
  echo "【merge 门禁】拒绝合并 PR #$PR：核对通过 $CHECKED/4。等 CI 全绿后重试：scripts/merge_pr.sh $PR" >&2
  exit 2
fi

# 测试注入点：不真的执行合并，只回报门禁已放行与将要执行的参数。
if [ -n "${AIUSAGE_MERGE_GATE_DRYRUN:-}" ]; then
  echo "MERGE-EXEC $PR $*"
  exit 0
fi

exec gh pr merge "$PR" "$@"
