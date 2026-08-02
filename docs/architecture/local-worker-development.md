# 本地服务端开发：wrangler dev + 本地 D1

> **状态**：生效（2026-08-02，#71）。
> 本文档描述的是**服务端**的本地开发入口。采集端（`pusher.py` 等）不受影响，照常用 Python。
> 决策背景见 [`server-path-consolidation-decision.md`](server-path-consolidation-decision.md)。

## 为什么换入口

按 #67 决策，服务端收敛为 Cloudflare Worker + D1 单实现。本地开发跑的应当就是**生产同款实现**，
这样服务端功能只需实现一次。

此前的 `python -m ai_usage_widget.cli server` 是一个平行的 Python 实现——它和 Worker 是两套代码，
两边行为必须一致但没有任何结构性机制保证。2026-08-01 一次交付里就因此撞了四次分叉
（详见 #67 正文）。那条路径现已**冻结**，随 #74 删除。

## 一条命令起来

```bash
scripts/dev_worker.sh --seed
```

它做三件事：把 `cloudflare/migrations/` 按序应用到本地 D1、灌入示例数据、起 `wrangler dev`。

| 参数 | 作用 |
| --- | --- |
| （无） | 应用 migrations 后起服务，库是空的 |
| `--seed` | 额外灌入示例数据，起来就有非空 summary |
| `--reset` | 先清空本地 D1 再来（schema 或数据脏了用这个） |
| `--port N` | 换端口，默认 8787 |

**前置条件**：Node >= 22（CI 用 22，wrangler 4 / vitest 4 跑不了更旧的）与 `npm ci`。
脚本会自己找 nvm 里的 22+ 并检查，缺了会明确报错而不是继续。

## 实测跑通的旅程

以下是 2026-08-02 在 Linux 开发机上的实际输出，不是示意：

```
$ scripts/dev_worker.sh --reset --seed --port 8802
=== 清空本地 D1 状态 ===
已删除 cloudflare/native-worker/.wrangler/state
=== 应用 migrations 到本地 D1 ===
│ 0001_initial_schema.sql                         │ ✅ │
│ 0002_source_accuracy.sql                        │ ✅ │
│ 0003_limit_window_stable_key.sql                │ ✅ │
│ 0004_source_report_states.sql                   │ ✅ │
│ 0005_audit_retention_indexes.sql                │ ✅ │
│ 0006_display_rollups.sql                        │ ✅ │
│ 0007_source_report_states_collector_version.sql │ ✅ │
=== 灌入示例数据 ===
示例数据已灌入
=== 启动本地 Worker ===
[wrangler:info] Ready on http://localhost:8802
```

读：

```bash
curl -H 'Authorization: Bearer contract-test-token' \
  'http://localhost:8802/api/summary?date=2026-06-03&period=week'
```

```
total_tokens : 7800，4 个来源
version_health.counts: {current:1, update_available:1, unsupported:1, unknown:1}
  macbook-pro · alice   → current
  linux-dev · bob       → update_available
  workstation-9 · cara  → unsupported
  mac-mini · dan        → unknown
```

写（用采集端真实产出的 payload，取自 #64 建立的 wire contract fixture）：

```bash
curl -X POST -H 'Authorization: Bearer contract-test-token' \
  -H 'Content-Type: application/json' \
  -d @<(python3 -c "
import json; r=json.load(open('cloudflare/native-worker/test/collector_payload_fixture.json'))[0]
p=r['payload']; p['observed_at']='2026-06-03T11:30:00+08:00'; print(json.dumps(p))") \
  http://localhost:8802/ingest
```

实测返回 `{"status":"accepted","facts_accepted":3,...}`，随后 `/api/summary` 即可读到该来源。

Token 是 `wrangler.local.toml` 里的 `AIUSAGE_TOKEN = "contract-test-token"`，本地固定值，
与生产无关，不是凭据。

## 离线能力：**能**（实测，非推断）

在**清空全部代理环境变量、不提供任何 Cloudflare API token** 的条件下实测：

- `wrangler dev --local` 正常启动，绑定显示 `D1 Database ... local`
- `wrangler d1 migrations apply --local` 正常应用全部 7 个 migration
- `wrangler d1 execute --local --file ...` 正常灌数据
- `/ingest`、`/api/summary`、`/api/mobile/summary`、`/api/health` 均正常响应

`wrangler` 与 `miniflare` 都是 `node_modules` 里的本地依赖（4.112.0 / 4.20260714.0），
不需要重新 `npm install`。脚本还显式设了 `WRANGLER_SEND_METRICS=false` 关掉遥测上报。

**唯一的联网前提**是首次 `npm ci`。之后完全离线可用。

**未验证**：完全物理断网（拔网线 / 防火墙全禁）下的行为。上面是在清代理 + 无 token 条件下
实测的，wrangler 未表现出任何对外请求失败的迹象，但这不等于对"物理断网"做过验证。

## 本地 D1 的状态放在哪

`cloudflare/native-worker/.wrangler/state/v3/d1/` —— 注意是**配置文件所在目录**，不是仓库根。

这一点容易踩：在仓库根删 `.wrangler/state` 会「删除成功」但什么也没重置，接着
`migrations apply` 报 `No migrations to apply!`（记录还在），于是你以为重置过了、
实际在旧库上继续跑。`--reset` 已按配置文件位置推导，不要手工删。

该目录含 SQLite 文件，已加入 `.gitignore`。

## migrations 为什么走 `migrations apply` 而不是手工灌 0001

`0001_initial_schema.sql` 是**累计快照**——0002/0003/0004/0005/0006 的成果都已回填进去
（0005 的两个审计索引由 #75 补齐）。所以手工只灌 0001 目前能拿到与迁移链一致的 schema，
仓库里有守卫测试钉住这一点。

但**这是靠测试维持的不变量，不是机制保证的**：新增迁移时如果忘了回填，0001 会再次落后，
只不过这次会被 `tests/test_d1_schema_migration.py` 拦下来。

`wrangler d1 migrations apply` 按序重放 0001..000N，与生产 D1 走同一条路径，
是唯一能保证本地与生产 schema 一致的方式。

## 与 Python 服务端的关系

`server.py` 那条链已按 #67 决策**冻结**，见 `.claude/rules/architecture.md`「Python 服务端冻结」。
它当前仍能跑（`test_web_server.py` 等仍绿），但：

- **不要**在它上面开发新功能或新字段——新字段的唯一去处是 `cloudflare/native-worker/src/*.ts`
- **不要**因为「Worker 加了、顺手同步一份」而改它
- 它随 #74 删除

## 已知限制

- 本地 D1 是 miniflare 的 SQLite 实现，与生产 D1 的行为差异（如并发、限额）不在此覆盖。
- 本地无 `SHADOW_INGEST_URL` 等 secret，影子上报路径在本地不生效。
- 生产部署、Secrets、线上 smoke 仍只能由 Ops Agent 在 macOS 侧执行，见
  `.claude/rules/cloudflare.md`。
