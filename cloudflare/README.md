# AI Usage Cloudflare Deployment

`aiusage.chunbai.com` 现在由 Cloudflare Worker 统一入口回源旧服务。Cloudflare 运维 Agent 负责账号内资源，程序开发 Agent 负责本目录中的 Worker、配置、测试和交接文档。

## 资源

- Pages project: `aiusage-dashboard`
- Worker: `aiusage-api`
- D1 binding: `AIUSAGE_DB`
- KV binding: `AIUSAGE_KV`
- R2 binding: `AIUSAGE_ASSETS`
- Domain: `aiusage.chunbai.com`

## 当前策略

Worker 发布 `cloudflare/aiusage-api-worker.js`，路由由 `wrangler.toml` 声明：

- `aiusage.chunbai.com/*`

本轮 Worker 回源这些用户入口和业务路径：

- `/`
- `/dashboard`
- `/login`
- `/static/*`
- `/api/*`
- `/ingest`
- `/ingest-limits`

Pages 静态化是后续任务，不作为本轮成功标准。`aiusage-dashboard` Pages 项目可以保留，但当前不要让它承载 Web 登录或 Dashboard 主路径。

## 应用侧部署命令

```bash
npm run cf:worker:deploy
```

`cf:pages:deploy` 只作为后续静态化准备，不用于本轮用户入口验收：

```bash
npm run cf:pages:deploy
```

真实 Cloudflare 部署和线上验证必须交给兄弟目录 `/Users/wangzhipeng/Documents/cloud-flare` 的运维 Agent，入口见 [`OPERATIONS_HANDOFF.md`](OPERATIONS_HANDOFF.md)。

## 当前回源

`ORIGIN_BASE_URL` 应为：

```text
https://vpn2.chunbai.com:8443
```

运维 Agent 当前如仍设置为 `https://vpn2.chunbai.com`，需要按 `wrangler.toml` 更新变量，否则 Worker 可能打到旧站点默认入口而不是 AI Usage API 服务。

后续如果启用 Tunnel，把 `ORIGIN_BASE_URL` 切到 Tunnel 可访问的 origin 即可；业务代码不需要知道 Tunnel token。

## 验证

Cloudflare Worker smoke 使用 `GET` 判断入口是否可用，不要用 `curl -I` / `HEAD` 判断。当前 Worker 和 origin 都按真实浏览器路径设计，`HEAD` 或本机代理/DNS 路径可能给出误导结果。

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

未登录 `/static/*` 预期可以是 401，因为当前 Python origin 把静态资源放在登录态后面。登录后带 session cookie 请求 `/static/dashboard.css` 和 `/static/dashboard.js` 必须是 200。

## 安全边界

不要上传或写入 Cloudflare：

- `data/usage.sqlite`
- `data/latest.json`
- `config/*.local.json`
- ingest token
- `.claude` / `.codex` 原始日志
- provider auth 文件或完整 provider response
