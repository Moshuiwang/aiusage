# AI Usage Cloudflare Deployment

`aiusage.chunbai.com` 现在由 Cloudflare Native Worker + D1 承载。Cloudflare 运维 Agent 负责账号内资源，程序开发 Agent 负责本目录中的 Worker、配置、测试和交接文档。

## 资源

- Pages project: `aiusage-dashboard`
- Worker: `aiusage-api`
- D1 binding: `AIUSAGE_DB`
- KV binding: `AIUSAGE_KV`
- R2 binding: `AIUSAGE_ASSETS`
- Domain: `aiusage.chunbai.com`

## 当前策略

当前生产读写都走 Cloudflare D1。VPN2 旧 AI Usage 后端已经下线，不再承载当前读写链路。当前事实见 [`../docs/architecture/cloudflare-migration-remaining-work.md`](../docs/architecture/cloudflare-migration-remaining-work.md)。

生产入口 Worker 路由由仓库根 `wrangler.toml` 声明：

- `aiusage.chunbai.com/*`

当前用户入口和业务路径：

- `/`
- `/dashboard`
- `/login`
- `/static/*`
- `/api/*`
- `/ingest`
- `/ingest-limits`

Pages 静态化不是当前用户入口。`aiusage-dashboard` Pages 项目可以保留，但不要让它承载 Web 登录或 Dashboard 主路径。

## 应用侧部署命令

```bash
npm run cf:worker:deploy
```

`cf:pages:deploy` 只作为后续静态化准备，不用于本轮用户入口验收：

```bash
npm run cf:pages:deploy
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

Web 入口验收：

```bash
curl -sS --max-time 12 -D - -o /dev/null \
  "https://aiusage.chunbai.com/"
curl -sS --max-time 12 -D - -o /dev/null \
  "https://aiusage.chunbai.com/static/dashboard.js"
```

未登录 `/static/*` 预期可以是 401。登录后带 session cookie 请求 `/static/dashboard.css` 和 `/static/dashboard.js` 必须是 200。

## 安全边界

不要上传或写入 Cloudflare：

- `data/usage.sqlite`
- `data/latest.json`
- `config/*.local.json`
- ingest token
- `.claude` / `.codex` 原始日志
- provider auth 文件或完整 provider response
