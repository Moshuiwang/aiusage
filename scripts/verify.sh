#!/usr/bin/env bash
# ai-usage 单一验证入口。
#
# 退出码 0 = 本机可验证范围内全部通过（证据等级 3：本地测试通过）。
# 跳过的部分一定会显式打印，绝不静默跳过。
#
# 用法:
#   scripts/verify.sh                 # 按改动面裁剪：不动 cloudflare/ 就不跑 Worker
#   scripts/verify.sh --full          # 强制全量（Python 约 85s + Worker 约 180s）
#   scripts/verify.sh --python-only   # 只跑 Python（约 85s）
#   scripts/verify.sh --explain-scope # 只打印裁剪判定，不跑任何测试
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PYTHON_ONLY=0
FORCE_FULL=0
EXPLAIN_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --python-only) PYTHON_ONLY=1 ;;
    --full) FORCE_FULL=1 ;;
    --explain-scope) EXPLAIN_ONLY=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 64 ;;
  esac
done

# --- 改动面裁剪 -------------------------------------------------------------
#
# 省下的是每次 3-4 分钟的 Worker 测试（#68 优化项 2）。但裁剪有一个危险的失败模式：
# 判据算错时该跑的不跑，而脚本照样退出 0、照样打印「证据等级 3」——静默漏跑。
# 所以这里一律保守：**只有能证明改动面不含 cloudflare/ 时才跳过**，任何不确定
# （不在 git 仓库、拿不到 base、git 命令失败）都退回全量。
#
# 改动面取并集，缺一不可：
#   - 工作区未提交改动（git status --porcelain，同 stop_gate.sh 的判据）
#   - 相对 base 的已提交改动——漏了这个，commit 之后再跑 verify 就会静默跳过 Worker
CHANGED_FILES=""
SCOPE_REASON=""
VERIFY_BASE="${AIUSAGE_VERIFY_BASE:-origin/main}"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  SCOPE_REASON="不在 git 仓库内，无法判定改动面"
else
  # `-uall`：不带它时 git 会把「新目录下的未跟踪文件」折叠成目录名（`tests/fixtures/`），
  # 于是任何比目录名更深的判据都匹配不到，该跑的测试被静默跳过。
  WORKTREE_CHANGES="$(git status --porcelain -uall 2>/dev/null | sed 's/^...//' | tr -d '"')"
  if git rev-parse --verify --quiet "$VERIFY_BASE" >/dev/null 2>&1; then
    COMMITTED_CHANGES="$(git diff --name-only "$VERIFY_BASE"...HEAD 2>/dev/null)"
    CHANGED_FILES="$(printf '%s\n%s\n' "$WORKTREE_CHANGES" "$COMMITTED_CHANGES" | grep -v '^$' | sort -u)"
  else
    SCOPE_REASON="拿不到 base ref（${VERIFY_BASE}），改动面不可信"
  fi
fi

RUN_WORKER=1
RUN_PYTHON=1
if [ "$PYTHON_ONLY" -eq 1 ]; then
  RUN_WORKER=0
  SCOPE_DECISION="指定了 --python-only"
elif [ "$FORCE_FULL" -eq 1 ]; then
  SCOPE_DECISION="指定了 --full"
elif [ -n "$SCOPE_REASON" ]; then
  SCOPE_DECISION="退回全量：$SCOPE_REASON"
elif [ -z "$CHANGED_FILES" ]; then
  SCOPE_DECISION="退回全量：改动面为空（相对 ${VERIFY_BASE} 无差异，可能是刚合并或 base 不对）"
else
  # Worker 侧：改动面涉及 cloudflare/ 才跑。
  #
  # 例外必须显式列出：#74 之后有三批产物的 owner（或 owner 绑定守卫）是 Worker 侧的测试，
  # 但它们的路径都不在 cloudflare/ 下——
  #   - `tests/fixtures/contract/api_contract_golden.json` → `golden-freshness.test.ts`
  #   - macOS owner fixture → `provider-slots-parity.test.ts`（由 golden 的 mobile 半边派生）
  #   - `tests/fixtures/verify_cloud/` → `verify-cloud-fixtures.test.ts`（mobile DTO 与版本块
  #     由 Worker owner 现算比对，#74 块 8 的接替守卫）
  # 漏了它们，单独手改那些文件时 Worker 测试会被静默跳过，
  # 而那正是唯一会为「被人手改过 / 已经陈旧」变红的地方。
  if printf '%s\n' "$CHANGED_FILES" | grep -qE '^(cloudflare/|tests/fixtures/contract/|tests/fixtures/verify_cloud/|clients/macos/Tests/AIUsageMenuBarCoreTests/Fixtures/)'; then
    SCOPE_DECISION="改动面涉及 cloudflare/ 或 Worker 拥有的合同 fixture"
  else
    RUN_WORKER=0
    SCOPE_DECISION="改动面不涉及 cloudflare/（相对 ${VERIFY_BASE}）"
  fi

  # Python 侧：判据**比「不含 cloudflare/」严格得多**，因为仍有 Python 测试会读
  # cloudflare/ 下的内容——migrations/（test_d1_schema_migration）、native-worker/test/ 的
  # 采集端 payload fixture（test_collector_payload_contract）、aiusage-api-worker.js、
  # worker.ts、README.md、OPERATIONS_HANDOFF.md（test_cloudflare_deployment 等治理测试）。
  # 按「改了 cloudflare/ 就跳 Python」做会静默漏跑这些。
  #
  # 唯一能证明不影响 Python 的范围是 TS 源码目录：实测 tests/ 与 scripts/ 下无一处读
  # cloudflare/native-worker/src/。所以只有改动面**全部**落在那里时才跳过 Python。
  if printf '%s\n' "$CHANGED_FILES" | grep -qvE '^cloudflare/native-worker/src/'; then
    :  # 有任何一个文件在该范围之外 → 照常跑 Python
  else
    RUN_PYTHON=0
    SCOPE_DECISION="${SCOPE_DECISION}；改动面全部在 cloudflare/native-worker/src/（Python 测试不读该目录）"
  fi
fi

if [ "$EXPLAIN_ONLY" -eq 1 ]; then
  echo "=== 裁剪判定 ==="
  echo "base          : $VERIFY_BASE"
  echo "判定          : $SCOPE_DECISION"
  echo "python=$([ "$RUN_PYTHON" -eq 1 ] && echo run || echo skip) worker=$([ "$RUN_WORKER" -eq 1 ] && echo run || echo skip)"
  echo "改动面（$(printf '%s\n' "$CHANGED_FILES" | grep -cv '^$' || echo 0) 个文件）："
  if [ -n "$CHANGED_FILES" ]; then
    printf '%s\n' "$CHANGED_FILES" | sed 's/^/  /'
  else
    echo "  （空）"
  fi
  exit 0
fi

FAILED=0
PY_RESULT="未运行"
WORKER_RESULT="未运行"
WORKER_SKIP_REASON=""

PY_SKIP_REASON=""
if [ "$RUN_PYTHON" -eq 0 ]; then
  PY_SKIP_REASON="$SCOPE_DECISION"
  echo "=== [1/2] Python 测试：跳过 ==="
  echo "原因：$SCOPE_DECISION"
  echo "如需强制跑：scripts/verify.sh --full"
  PY_CODE=0
  PY_OUT=""
else
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
fi

echo
if [ "$RUN_WORKER" -eq 0 ]; then
  WORKER_SKIP_REASON="$SCOPE_DECISION"
  echo "=== [2/2] Cloudflare Worker 验证：跳过 ==="
  echo "原因：$SCOPE_DECISION"
  echo "如需强制跑：scripts/verify.sh --full；查看判定依据：scripts/verify.sh --explain-scope"
else
  echo "=== [2/2] Cloudflare Worker 验证（TypeScript + vitest） ==="
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
    WK_OUT="$(npm run cf:native:verify 2>&1)"
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
    # “本应执行但环境不具备”不是按改动面合法裁剪，不能报等级 3。
    FAILED=1
  fi
fi

echo
echo "================= 证据摘要 ================="
if [ -n "$PY_SKIP_REASON" ]; then
  echo "Python 测试   : 未运行（${PY_SKIP_REASON}）"
else
  echo "Python 测试   : $PY_RESULT"
fi
if [ -n "$WORKER_SKIP_REASON" ]; then
  echo "Worker 验证   : 未运行（${WORKER_SKIP_REASON}）"
else
  echo "Worker 验证   : $WORKER_RESULT"
fi
echo
echo "统一入口未覆盖、需按对应环境另行验证的项："
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
