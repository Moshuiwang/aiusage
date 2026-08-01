#!/usr/bin/env bash
# ai-usage 单一验证入口。
#
# 退出码 0 = 本机可验证范围内全部通过（证据等级 3：本地测试通过）。
# 跳过的部分一定会显式打印，绝不静默跳过。
#
# 用法:
#   scripts/verify.sh                # 全量（Python 约 85s + Worker 约 180s）
#   scripts/verify.sh --python-only  # 只跑 Python（约 85s）
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PYTHON_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --python-only) PYTHON_ONLY=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 64 ;;
  esac
done

FAILED=0
PY_RESULT="未运行"
WORKER_RESULT="未运行"
WORKER_SKIP_REASON=""

echo "=== [1/2] Python 测试（stdlib unittest，无第三方依赖） ==="
PY_OUT="$(PYTHONPATH=src python3 -m unittest discover -s tests 2>&1)"
PY_CODE=$?
if [ "$PY_CODE" -eq 0 ]; then
  # 测试自身会往 stdout 打 JSON，只摘出 unittest 的结论行
  echo "$PY_OUT" | grep -E '^(Ran [0-9]+ tests|OK|FAILED)' || true
else
  echo "$PY_OUT" | grep -E '^(FAIL|ERROR): ' | head -20
  echo "--- 详情（已滤掉测试自身的 HTTP / JSON 输出）---"
  echo "$PY_OUT" | grep -vE '127\.0\.0\.1 - - \[|^\{|^[.sEFx]+$' | tail -25
fi
if [ "$PY_CODE" -eq 0 ]; then
  PY_RESULT="通过（$(echo "$PY_OUT" | grep -oE 'Ran [0-9]+ tests' | tail -1)）"
else
  PY_RESULT="失败"
  FAILED=1
fi

echo
if [ "$PYTHON_ONLY" -eq 1 ]; then
  WORKER_SKIP_REASON="指定了 --python-only"
  echo "=== [2/2] Cloudflare Worker 测试：跳过（--python-only） ==="
else
  echo "=== [2/2] Cloudflare Worker 测试（vitest） ==="
  # 本项目要求 Node >= 22（CI 用 22）。系统 node 可能更旧，优先用 nvm 里的 22+。
  NVM_NODE="$(ls -d "$HOME"/.nvm/versions/node/v2[2-9].* 2>/dev/null | sort -V | tail -1)"
  if [ -n "$NVM_NODE" ]; then
    export PATH="$NVM_NODE/bin:$PATH"
  fi
  NODE_MAJOR="$(node -v 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/')"

  if [ -z "${NODE_MAJOR:-}" ]; then
    WORKER_SKIP_REASON="未找到 node"
  elif [ "$NODE_MAJOR" -lt 22 ]; then
    WORKER_SKIP_REASON="Node 版本过低（当前 v${NODE_MAJOR}，需要 >= 22）"
  elif [ ! -d node_modules ]; then
    WORKER_SKIP_REASON="node_modules 不存在，请先运行 npm ci"
  else
    WK_OUT="$(npm run cf:native:test 2>&1)"
    WK_CODE=$?
    echo "$WK_OUT" | tail -6
    if [ "$WK_CODE" -eq 0 ]; then
      WORKER_RESULT="通过（$(echo "$WK_OUT" | grep -oE 'Tests +[0-9]+ passed' | tail -1)）"
    else
      WORKER_RESULT="失败"
      FAILED=1
    fi
  fi
  if [ -n "$WORKER_SKIP_REASON" ]; then
    echo "跳过：$WORKER_SKIP_REASON"
  fi
fi

echo
echo "================= 证据摘要 ================="
echo "Python 测试   : $PY_RESULT"
if [ -n "$WORKER_SKIP_REASON" ]; then
  echo "Worker 测试   : 未运行（$WORKER_SKIP_REASON）"
else
  echo "Worker 测试   : $WORKER_RESULT"
fi
echo
echo "本机（Linux）无法验证、必须回 Mac 侧执行的项："
echo "  - iOS / macOS Swift 测试与构建（swift test / xcodebuild / xcodegen）"
echo "  - 真实 Cloudflare 部署、Secrets、线上 smoke（走 Ops Agent）"
echo "  - 真机 iPhone / Apple Watch 安装与截图验收"
echo "  - 真实 ingest 上报与 ccusage 真实采集（无凭据、未装 ccusage）"
echo
if [ "$FAILED" -eq 0 ]; then
  echo "结论：本机可验证范围内全部通过 → 证据等级 3（本地测试通过）。"
  echo "      证据等级 4 及以上（CI / 部署 / 真机 / 回源核对）尚未验证。"
else
  echo "结论：存在失败项，未达证据等级 3。"
fi
echo "==========================================="
exit "$FAILED"
