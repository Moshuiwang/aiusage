# Native Worker Staging Deploy Runbook

目标：把原生 TypeScript Worker 部署到 Cloudflare staging Worker，拿到 `*.workers.dev` 预发地址；不要改 live 入口。

## 配置

- 配置文件：`cloudflare/native-worker/wrangler.toml`
- Worker name：`aiusage-native-staging`
- 入口：`cloudflare/native-worker/src/index.ts`
- D1 binding：`AIUSAGE_DB`
- D1 database：`aiusage-prod-db`
- 访问方式：`workers_dev = true`，使用 Cloudflare 分配的 `*.workers.dev` staging URL
- 不配置 custom route；不要把 live 入口指向这个 Worker。

## Secrets

在部署前由 ops 设置：

```bash
pnpm exec wrangler secret put AIUSAGE_TOKEN --config cloudflare/native-worker/wrangler.toml
pnpm exec wrangler secret put AIUSAGE_SESSION_SECRET --config cloudflare/native-worker/wrangler.toml
```

- `AIUSAGE_TOKEN`：使用当前生产 ingest/api token 的同一个值。
- `AIUSAGE_SESSION_SECRET`：使用 Python 服务当前的同一个 session secret。
- 如果暂时不设置 `AIUSAGE_SESSION_SECRET`，Worker 会回退使用 primary token；cookie-parity 测试已确认该 fallback 与 Python 口径匹配。

不要把 `AIUSAGE_TOKEN` 或 `AIUSAGE_SESSION_SECRET` 写入 toml。

## Dry Run

本地只构建、不上传：

```bash
pnpm exec wrangler deploy --dry-run --outdir tmp/native-dryrun --config cloudflare/native-worker/wrangler.toml
```

## Deploy

由 ops 执行：

```bash
pnpm exec wrangler deploy --config cloudflare/native-worker/wrangler.toml
```

部署后记录 Cloudflare 输出的 `*.workers.dev` URL，后续 smoke 都用这个 staging URL。

## Smoke

假设 staging URL 为 `$STAGING_URL`：

```bash
curl -sS -D - -o /dev/null "$STAGING_URL/"
curl -sS -D - -o /dev/null "$STAGING_URL/api/mobile/summary?period=today"
curl -sS -D - "$STAGING_URL/api/health"
```

检查项：

- `GET /` 返回登录页，HTTP 200。
- `GET /api/mobile/summary?period=today` 不带认证返回 HTTP 401。
- `GET /api/health` 返回当前 Worker 的健康状态；如果 D1 或环境变量缺失，应能清楚暴露 staging 配置问题，而不是影响 live 入口。
