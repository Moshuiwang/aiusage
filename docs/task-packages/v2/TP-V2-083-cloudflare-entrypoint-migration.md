# TP-V2-083 Cloudflare Entrypoint Migration

Version: V2
ID: TP-V2-083
Status: completed
Type: implementation
Depends on: Cloudflare resources created by operations agent
Parallel with: none

## Goal

把 `aiusage.chunbai.com` 从占位入口推进到可部署的 AI Usage Cloudflare 程序侧入口：Worker 统一入口回源旧服务，先保证 Web 登录、Dashboard、静态资源、API、`/ingest` 和 `/ingest-limits` 在 Cloudflare 域名下可用。

## Context

Cloudflare 运维 Agent 已创建：

- Pages：`aiusage-dashboard`
- Worker：`aiusage-api`
- D1：`aiusage-dev-db`，binding `AIUSAGE_DB`
- KV：`aiusage-dev-kv`，binding `AIUSAGE_KV`
- R2：`aiusage-dev-assets`，binding `AIUSAGE_ASSETS`
- Routes：当前程序侧目标为 `aiusage.chunbai.com/*`

当前产品仍是开发状态，可以接受激进切换；但 token、SQLite、原始 usage 日志和本地 credential 仍不能进入 Cloudflare 静态或源码。

## Scope

- 新增 `wrangler.toml`，绑定运维已创建的 Worker / D1 / KV / R2。
- 新增 Cloudflare Worker 回源代码，先保护现有 Python Web 登录、Dashboard、API 和 SQLite 写入链路。
- 保留 Pages 部署脚本作为后续静态化准备；Pages 静态化不作为本轮成功标准。
- 新增合同测试，锁定路由、缓存、安全和部署入口。
- 记录运维交接要求：Cloudflare 账号侧部署必须由兄弟目录 `/Users/wangzhipeng/Documents/cloud-flare` 的运维 Agent 通过 Codex CLI 执行；当前 Worker 环境里的 `ORIGIN_BASE_URL` 应为 `https://vpn2.chunbai.com:8443`，或后续切到 Tunnel origin。

## Out of Scope

- 不把 SQLite 迁到 D1。
- 不把 `/ingest` 写入逻辑改写为 Worker 原生。
- 不把 Web 登录改写成 Pages Function。
- 不上传 `data/usage.sqlite`、`config/*.local.json`、token、`.claude`、`.codex`。
- 不改 iOS / macOS 客户端默认域名。
- 不由应用 Agent 启动或配置 Cloudflare Tunnel connector；这仍由 Cloudflare 运维 Agent 执行。

## Red Test

新增 `tests/test_cloudflare_deployment.py`，先断言以下文件和合同不存在：

- `wrangler.toml`
- `cloudflare/aiusage-api-worker.js`
- `package.json` 中的 Pages / Worker 部署脚本
- Cloudflare 资源 binding、整站 Worker route、Web/API/ingest 回源路径、POST body 转发、禁缓存和无 secret literal 约束

## Implementation

1. 新增 Cloudflare Worker 回源实现。
2. 新增 wrangler 配置，绑定运维已创建资源。
3. 新增 npm scripts，支持部署 Worker 和 Pages。
4. 根据 AI Review 修正 Worker 为统一入口回源：`/`、`/dashboard`、`/login`、`/static/*`、`/api/*`、`/ingest`、`/ingest-limits`。
5. 新增 Cloudflare README 和运维交接说明，说明应用 Agent 与 Cloudflare 运维 Agent 的分工和验证命令。
6. 跑合同测试、静态 Dashboard 测试和 scoped AI Review。

## Acceptance Criteria

- `wrangler.toml` 使用 `aiusage-api`、`AIUSAGE_DB`、`AIUSAGE_KV`、`AIUSAGE_ASSETS`。
- `wrangler.toml` 使用 `aiusage.chunbai.com/*`，避免 Web 页面、登录和静态资源落到 Pages 静态壳。
- Worker 对 `/`、`/dashboard`、`/login`、`/static/*`、`/api/*`、`/ingest`、`/ingest-limits` 回源旧服务，并对这些路径设置 `Cache-Control: no-store`。
- Worker 对 POST 路径显式读取 body 后转发，降低旧 Python origin 拿不到请求体的风险。
- Pages 部署脚本保留为后续静态化准备；Pages 静态化不作为本轮成功标准。
- 源码不包含真实 ingest token、SQLite、local config 或原始日志。
- 本地测试和 scoped AI Review 通过。
- Cloudflare 账号侧部署和线上 smoke 由兄弟目录 `/Users/wangzhipeng/Documents/cloud-flare` 的运维 Agent 执行。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_cloudflare_deployment tests.test_dashboard_static -v
```

本地最终检查：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
node --check cloudflare/aiusage-api-worker.js
python3 -m json.tool package.json >/dev/null
```

Scoped AI Review 记录：

- `reviews/20260621-214554-codex-cloudflare-aiusage-migration-local-0f94445-cf001.md`
- `reviews/20260621-221333-codex-cloudflare-aiusage-migration-local-0f94445-cf002.md`

Cloudflare 线上验证由运维 Agent 在 `/Users/wangzhipeng/Documents/cloud-flare` 中通过 Codex CLI 执行。建议命令入口：

```bash
codex exec --cd /Users/wangzhipeng/Documents/cloud-flare --skip-git-repo-check "<Cloudflare 运维任务说明>"
```

线上 smoke 至少包括：

```bash
curl -sS --max-time 12 -D - -o /dev/null "https://aiusage.chunbai.com/"
curl -sS --max-time 12 -D - -o /dev/null "https://aiusage.chunbai.com/static/dashboard.js"
curl -sS --max-time 12 -D - -o /dev/null "https://aiusage.chunbai.com/api/mobile/summary?period=all"
```

不要用 `curl -I` / `HEAD` 判断本 Worker 是否正常；必要时临时加 `--resolve aiusage.chunbai.com:443:<Cloudflare IP>` 区分本机 DNS/代理问题和生产入口问题。

2026-06-21 用户浏览器验收已确认：

- `https://aiusage.chunbai.com/` 可打开登录页。
- 登录后 `https://aiusage.chunbai.com/dashboard` 可打开 Dashboard。
- Dashboard 样式和脚本正常加载，页面显示 live 数据。
- 本机代理问题已定位为 Shadowrocket/MacPacket 路径问题，不需要改 Cloudflare 配置。

## Handoff

- 汇报 Cloudflare 代码侧新增文件。
- 汇报本地测试。
- 汇报 scoped AI Review。
- 汇报是否已启动 Cloudflare 运维 sub-agent。
- 汇报 Cloudflare 运维 Agent 返回的线上验证结果；如果 DNS、TLS、route 或 token 权限阻塞，明确阻塞点。
