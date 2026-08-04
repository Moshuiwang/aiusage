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

# `-uall` 与 `scripts/verify.sh` 的改动面口径保持一致：不带它时 git 会把
# 「新目录下的未跟踪文件」折叠成目录名。对本脚本现在这两条顶层前缀判据没有行为差别
# （折叠后仍以 src/ 或 tests/ 开头），但两个脚本共用同一套判据，
# 留一个不带 -uall 的会让将来任何更深的路径判据在这里静默失效。
CHANGED="$(git status --porcelain -uall 2>/dev/null | sed 's/^...//')"

# 资源盘点（#68 补记二）：git status 干净不等于收口干净。
# 只查最痛的一种残留——wrangler dev 曾在收口宣布「无残留」后被发现挂了 78 分钟。
#
# 判据必须是**可执行文件 + argv**，不能是 `pgrep -f` 那样的整条命令行文本匹配（#86）：
#   - `pgrep -f` 会匹配到**只是提到**这个词组的进程——`bash -c` 的 argv 就是整段脚本文本，
#     于是调用方 shell、兄弟进程、甚至一条讨论它的命令都会被当成残留报出来，
#     而 `ps -p <PID>` 查过去是空的。旧注释「本脚本自身命令行不含 wrangler，不会自匹配」
#     只对脚本自己成立，不覆盖父 shell 与兄弟进程。
#   - 同一条 `pgrep -f 'wrangler.* dev\b'` 又**漏掉**了真正的 worker 进程：
#     `workerd serve ...` 的命令行里根本没有 `wrangler` 子串。
#
# 现在的判据：
#   A) 可执行文件是 node / wrangler，且 argv 里同时有 wrangler 入口与独立的 `dev` 参数。
#      这一条盖住 `wrangler dev`、`npm exec wrangler dev`、
#      `node .../wrangler-dist/cli.js dev` 三种形态，而 `bash -c "...wrangler dev..."`
#      的可执行文件是 bash，天然被排除。
#   B) **孤儿** `workerd`（父进程已退出）。
#      workerd 本身不算残留：它永远是 `wrangler dev` 或 vitest/miniflare 的子进程，
#      没有独立生命周期，把「有父进程的 workerd」算成残留会让每次跑完 Worker 测试、
#      或后台还有 verify 在跑时都收不了口，门禁很快会被人用 .skip-stop-gate 绕开。
#      父进程已经没了的 workerd 就不一样了——它谁也不属于，正是那种占着端口没人发现的泄漏。
#   两条都排除**当前进程及其全部祖先**：hook 自己是 Claude Code（node）拉起来的，
#   而 node 的 argv 里完全可能带着讨论 wrangler dev 的文本。

# 测试注入点：给定一张固定的进程表（pid ppid comm args），让判据可以离线回归。
process_snapshot() {
  if [ -n "${AIUSAGE_STOP_GATE_PS:-}" ] && [ -r "${AIUSAGE_STOP_GATE_PS}" ]; then
    cat "$AIUSAGE_STOP_GATE_PS"
  else
    ps -eo pid=,ppid=,comm=,args= 2>/dev/null
  fi
}

# 当前进程及其全部祖先的 PID 列表（空格分隔，两端各留一个空格便于整词匹配）。
self_chain() {
  local snapshot="$1" pid="$2" guard=0 chain=" "
  while [ -n "$pid" ] && [ "$pid" != "0" ] && [ "$pid" != "1" ] && [ "$guard" -lt 64 ]; do
    chain="$chain$pid "
    pid="$(printf '%s\n' "$snapshot" | awk -v want="$pid" '$1 == want { print $2; exit }')"
    guard=$((guard + 1))
  done
  printf '%s' "$chain"
}

find_residue() {
  local snapshot chain executable argv0
  snapshot="$(process_snapshot)"
  chain="$(self_chain "$snapshot" "${AIUSAGE_STOP_GATE_SELF_PID:-$$}")"
  printf '%s\n' "$snapshot" | while read -r pid ppid comm args; do
    [ -z "$pid" ] && continue
    case "$chain" in *" $pid "*) continue ;; esac
    executable="${comm##*/}"
    case "$executable" in
      node|nodejs|wrangler|workerd) ;;
      *)
        # macOS 的 `ps comm` 只有 16 字节，绝对路径会被截成 `/Users/...`，
        # 不能据此否定真实 node/workerd。argv 第一个词仍是可执行文件路径；
        # bash -c 的第一个词是 bash，所以不会重引入“只是提到 wrangler dev”误报。
        argv0="${args%% *}"
        executable="${argv0##*/}"
        ;;
    esac
    case "$executable" in
      node|nodejs|wrangler)
        case "$args" in *wrangler*) ;; *) continue ;; esac
        case " $args " in *" dev "*) printf '%s\n' "$pid" ;; esac
        ;;
      workerd)
        [ "$ppid" = "1" ] && printf '%s\n' "$pid"
        ;;
    esac
  done
}

RESIDUE="$(find_residue)"

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
    echo "收口口径（2026-08-03 起）：跑改动对应的 targeted Worker 测试并在汇报中给出结果："
    echo "    npx --prefix cloudflare/native-worker vitest run --config cloudflare/native-worker/vitest.config.ts <改动相关的 test 文件>"
    echo "全量套件交给 PR CI（合并唯一入口 scripts/merge_pr.sh 强制四个 check 全 SUCCESS）；"
    echo "本地全量 scripts/verify.sh --full 仍可用，但只是可选复核，不是收口必要条件。"
    echo "targeted 已绿、或确实无法在本机验证时，创建 .claude/.skip-stop-gate（一次性）"
    echo "并在收口汇报中写明依据与证据等级。"
  } >&2
  rm -f "$LOG"
  exit 2
fi

if [ -n "$RESIDUE" ]; then
  {
    echo "【收口被阻止】发现残留的本地开发服务进程（PID: $(echo "$RESIDUE" | tr '\n' ' ')）。"
    echo "判据是可执行文件 + argv：长驻的 wrangler dev（含 node .../wrangler-dist/cli.js dev），"
    echo "或父进程已退出的孤儿 workerd。先 ps -p <PID> 看一眼再动手。"
    echo "按 PID 逐个 kill 并回读确认（父进程链要一起清，fuser -k 只杀监听那一个）。"
    echo "确认需要保留时创建 .claude/.skip-stop-gate。"
  } >&2
  rm -f "$LOG"
  exit 2
fi

rm -f "$LOG"
exit 0
