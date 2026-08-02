#!/usr/bin/env bash
# Claude Code Stop hook：代码有改动时强制验证，未通过则阻止收口。
#
# 退出码语义（Claude Code 约定）：
#   0 = 放行
#   2 = 阻止本轮结束，stderr 的内容会回传给 Claude 作为反馈
#
# 设计取舍：全量测试较慢（Python 约 85s、Worker 约 180s），所以**按改动范围触发**：
#   - 只读对话 / 纯文档改动        -> 直接放行，零开销
#   - src/ 或 tests/ 有改动         -> 跑 Python 全量，不绿则阻止
#   - cloudflare/ 有改动            -> 不自动跑（太慢），但强制显式交代
set -uo pipefail
cd "$(dirname "$0")/.." || exit 0

# 不在 git 仓库时不拦截
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

CHANGED="$(git status --porcelain 2>/dev/null | sed 's/^...//')"

# 资源盘点（#68 补记二）：git status 干净不等于收口干净。
# 只查最痛的一种残留——wrangler dev 曾在收口宣布「无残留」后被发现挂了 78 分钟。
# 模式要能盖住整条进程链：npm exec wrangler dev / sh -c wrangler dev /
# node .bin/wrangler dev / node wrangler-dist/cli.js dev（最后一层不含字面 "wrangler dev"）。
# 这里的 pgrep -f 是只读盘点（合法用途）；本脚本自身命令行不含 wrangler，不会自匹配。
RESIDUE="$(pgrep -f 'wrangler.* dev\b' 2>/dev/null || true)"

NEED_PY=0
NEED_WORKER=0
echo "$CHANGED" | grep -qE '(^|")(src/|tests/)' && NEED_PY=1
echo "$CHANGED" | grep -qE '(^|")cloudflare/'   && NEED_WORKER=1

[ "$NEED_PY" -eq 0 ] && [ "$NEED_WORKER" -eq 0 ] && [ -z "$RESIDUE" ] && exit 0

# 允许显式跳过一次（用于确实无法在本机验证的场景）
if [ -f .claude/.skip-stop-gate ]; then
  rm -f .claude/.skip-stop-gate
  echo "已按 .claude/.skip-stop-gate 跳过本次门禁（该标记为一次性，已删除）。" >&2
  exit 0
fi

LOG="$(mktemp -t aiusage-stop-gate.XXXXXX)"

if [ "$NEED_PY" -eq 1 ]; then
  if ! PYTHONPATH=src python3 -m unittest discover -s tests >"$LOG" 2>&1; then
    {
      echo "【收口被阻止】src/ 或 tests/ 有改动，但 Python 测试未通过。"
      echo "先修复失败用例再收口；不要弱化断言或删测试来让它变绿。"
      echo "--- 失败用例 ---"
      grep -E '^(FAIL|ERROR): ' "$LOG" | head -20
      echo "--- 详情（已滤掉测试自身的 HTTP / JSON 输出）---"
      grep -vE '127\.0\.0\.1 - - \[|^\{|^[.sEFx]+$' "$LOG" | tail -25
    } >&2
    rm -f "$LOG"
    exit 2
  fi
fi

if [ "$NEED_WORKER" -eq 1 ]; then
  {
    echo "【收口被阻止】cloudflare/ 有改动。"
    echo "Worker 测试约需 180s，未在本门禁中自动运行。请执行："
    echo "    scripts/verify.sh"
    echo "并在收口汇报中给出 Worker 测试结果与证据等级。"
    echo "确实无法在本机验证时，创建 .claude/.skip-stop-gate 并在汇报中写明原因。"
  } >&2
  rm -f "$LOG"
  exit 2
fi

if [ -n "$RESIDUE" ]; then
  {
    echo "【收口被阻止】发现残留的 wrangler dev 进程（PID: $(echo "$RESIDUE" | tr '\n' ' ')）。"
    echo "按 PID 逐个 kill 并回读确认（父进程链要一起清，fuser -k 只杀监听那一个）。"
    echo "如果是正在运行的 verify/测试起的，等它结束；确认需要保留时创建 .claude/.skip-stop-gate。"
  } >&2
  rm -f "$LOG"
  exit 2
fi

rm -f "$LOG"
exit 0
