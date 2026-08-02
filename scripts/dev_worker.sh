#!/usr/bin/env bash
# 本地服务端开发入口：wrangler dev + 本地 D1（#71）。
#
# 跑的就是生产同款实现（Cloudflare Worker + D1），所以服务端功能只需实现一次。
# Python 服务端（server.py 那条链）已按 #67 决策冻结，不再是开发入口。
#
# 用法:
#   scripts/dev_worker.sh              # 应用 migrations 后起服务
#   scripts/dev_worker.sh --seed       # 额外灌入示例数据，起来就有非空 summary
#   scripts/dev_worker.sh --reset      # 先清空本地 D1 再来（schema 或数据脏了用这个）
#   scripts/dev_worker.sh --port 8888  # 换端口（默认 8787）
#
# 离线可用：不需要 Cloudflare 账号、API token 或外网。实测见 docs/architecture/
# local-worker-development.md「离线能力」一节。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

CONFIG="cloudflare/native-worker/wrangler.local.toml"
DB_NAME="aiusage-native-readonly-local-db"
PORT=8787
DO_SEED=0
DO_RESET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --seed) DO_SEED=1 ;;
    --reset) DO_RESET=1 ;;
    --port) shift; PORT="${1:-8787}" ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 64 ;;
  esac
  shift
done

# 本项目要求 Node >= 22（CI 用 22，vitest 4 / wrangler 4 跑不了更旧的）。
NVM_NODE="$(ls -d "$HOME"/.nvm/versions/node/v2[2-9].* 2>/dev/null | sort -V | tail -1)"
if [ -n "$NVM_NODE" ]; then
  export PATH="$NVM_NODE/bin:$PATH"
fi
NODE_MAJOR="$(node -v 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/')"
if [ -z "${NODE_MAJOR:-}" ] || [ "$NODE_MAJOR" -lt 22 ]; then
  echo "需要 Node >= 22（当前：$(node -v 2>/dev/null || echo '未找到 node')）" >&2
  echo "本机若用 nvm：nvm use 22" >&2
  exit 1
fi
if [ ! -d node_modules ]; then
  echo "node_modules 不存在，先跑：npm ci" >&2
  exit 1
fi

# wrangler 默认会往 Cloudflare 发遥测。本地开发不需要，也让离线更干净。
export WRANGLER_SEND_METRICS=false

wrangler_local() {
  env -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy \
    npx wrangler "$@" --config "$CONFIG" --local
}

if [ "$DO_RESET" -eq 1 ]; then
  echo "=== 清空本地 D1 状态 ==="
  # state 落在**配置文件所在目录**，不是 cwd。删错地方的表现是
  # 「已删除」照打、migrations 却报 No migrations to apply（记录还在），
  # 然后你以为重置过了、实际在旧库上继续跑。
  STATE_DIR="$(dirname "$CONFIG")/.wrangler/state"
  if [ -d "$STATE_DIR" ]; then
    rm -rf "$STATE_DIR"
    echo "已删除 $STATE_DIR"
  else
    echo "$STATE_DIR 不存在，无需清理"
  fi
fi

echo "=== 应用 migrations 到本地 D1 ==="
# 用 wrangler 原生的 migrations apply，而不是手工 execute 单个 .sql：
# 它会按序重放 0001..000N，与生产 D1 走的是同一条路径。
# 手工只灌 0001 依赖「0001 这份累计快照没有落后于迁移链」这个不变量——该不变量目前由
# tests/test_d1_schema_migration.py 的守卫维持（#75 补回 0005 索引后建立），但它是测试维持的，
# 不是机制保证的。走 migrations apply 不依赖这个前提。
if ! wrangler_local d1 migrations apply "$DB_NAME" 2>&1 | tail -20; then
  echo "migrations 应用失败" >&2
  exit 1
fi

if [ "$DO_SEED" -eq 1 ]; then
  echo
  echo "=== 灌入示例数据 ==="
  # 复用跨实现 parity 的 seed：4 台设备、多 provider、版本四态齐全，
  # 起来就能在 /api/summary 看到非空数据，不必自己造。
  SEED_OUT="$(wrangler_local d1 execute "$DB_NAME" \
    --file cloudflare/native-worker/test/seed.sql 2>&1)"
  # 不能只 tail 几行了事：灌库失败时服务照样起得来，只是 summary 一直是空的，
  # 而人会以为「本地就是没数据」而不是「seed 挂了」。
  if printf '%s' "$SEED_OUT" | grep -qiE 'error|failed|✘'; then
    echo "$SEED_OUT" | tail -20
    echo
    echo "seed 灌入失败。若是主键冲突，说明库里已有数据，用 --reset 重来。" >&2
    exit 1
  fi
  echo "$SEED_OUT" | grep -oE '[0-9]+ (rows?|commands?) (written|executed)' | tail -2 || true
  echo "示例数据已灌入"
fi

echo
echo "=== 启动本地 Worker ==="
echo "  地址   : http://localhost:${PORT}"
echo "  Token  : contract-test-token（wrangler.local.toml 里的 AIUSAGE_TOKEN）"
echo
echo "  试一下："
echo "    curl -H 'Authorization: Bearer contract-test-token' \\"
echo "      'http://localhost:${PORT}/api/summary?date=2026-06-03&period=week'"
echo
env -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy \
  npx wrangler dev --config "$CONFIG" --local --port "$PORT"
