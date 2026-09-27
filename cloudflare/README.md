# AI Usage Cloudflare Deployment

`aiusage.chunbai.com` 现在由 Cloudflare Native Worker + D1 承载。Cloudflare 运维 Agent 负责账号内资源，程序开发 Agent 负责本目录中的 Worker、配置、测试和交接文档。

## 资源

- Worker: `aiusage-api`
- D1 binding: `AIUSAGE_DB` → `aiusage-prod-db`
- R2 binding: `AIUSAGE_BACKUPS` → `aiusage-backups`
- Domain: `aiusage.chunbai.com`

## 当前策略

当前生产读写都走 Cloudflare D1。VPN2 旧 AI Usage 后端、legacy proxy 和 Pages Dashboard 均不再承载当前用户链路。

生产入口 Worker 路由由 `cloudflare/native-worker/wrangler.toml` 声明：

- `aiusage.chunbai.com/*`

当前用户入口和业务路径：

- `/api/*`
- `/ingest`
- `/ingest-limits`

网页看板（`/`、`/dashboard`、登录页、`/static/*`）已随 #199 整体废弃，只保留 macOS 菜单栏
与 iPhone 端消费的 `/api/*`。旧 `aiusage-dashboard` Pages 项目已删除。

## 应用侧部署命令

```bash
npm run cf:worker:deploy
```

真实 Cloudflare 部署和线上验证必须交给 `/Users/wangzhipeng/Documents/ops` 的运维 Agent，入口见 [`OPERATIONS_HANDOFF.md`](OPERATIONS_HANDOFF.md)。不要假定旧 `cloud-flare` 目录存在。

## 验证

Cloudflare Worker smoke 使用 `GET` 判断入口是否可用，不要用 `curl -I` / `HEAD` 判断。当前 Worker 按真实浏览器路径设计，`HEAD` 或本机代理/DNS 路径可能给出误导结果。

推荐固定写法：

- `curl -D - -o /dev/null` 查看状态码和关键响应头。
- 必要时临时加 `--resolve aiusage.chunbai.com:443:<Cloudflare IP>` 区分本机 DNS/代理问题和生产入口问题。
- 不在输出里打印 token、cookie 或响应正文。

无 token 情况下，API 真实回源的预期是返回认证错误，而不是占位页：

```bash
curl -sS --max-time 12 -D - -o /dev/null \
  "https://aiusage.chunbai.com/api/mobile/summary?period=all"
```

有 token 时再验证：

```bash
curl -sS --max-time 12 -H "Authorization: Bearer <token>" \
  -D - -o /dev/null \
  "https://aiusage.chunbai.com/api/mobile/summary?period=all"
```

网页看板已随 #199 整体废弃：`/`、`/dashboard`、`/login`、`/static/*` 现在与其它未知路径一样
返回标准 404，不再有专门的入口验收步骤。

## 安全边界

不要上传或写入 Cloudflare：

- `data/usage.sqlite`
- `data/latest.json`
- `config/*.local.json`
- ingest token
- `.claude` / `.codex` 原始日志
- provider auth 文件或完整 provider response
