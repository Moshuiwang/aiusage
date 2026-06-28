# AI Usage Cloudflare Operations Handoff

## 入口

Cloudflare 账号侧操作必须由兄弟目录的运维 Agent 执行：

```bash
codex exec --cd /Users/wangzhipeng/Documents/cloud-flare --skip-git-repo-check "<Cloudflare 运维任务说明>"
```

运维 Agent 必须读取 `/Users/wangzhipeng/Documents/cloud-flare/AGENTS.md`，并使用该目录自己的 `.env`。不要读取或输出 .env、Cloudflare token、ingest token、SQLite 或原始 usage 日志。

## 应用侧输入

- Native Worker：`/Users/wangzhipeng/Documents/ai-usage-widget/cloudflare/native-worker/`
- 入口 Worker / 路由配置：`/Users/wangzhipeng/Documents/ai-usage-widget/wrangler.toml`
- 目标入口 Worker：`aiusage-api`
- 目标 Native Worker：`aiusage-native-staging`
- D1：`aiusage-prod-db`
- 目标域名：`aiusage.chunbai.com`
- 当前 route：`aiusage.chunbai.com/*`
- 当前 canonical store：Cloudflare D1
- VPN2：旧 AI Usage 后端已下线，只作为历史回退/审计对象，不参与当前读写。

## 运维 Agent 任务

1. 使用 Cloudflare 凭据部署或检查 Native Worker / 入口 Worker。
2. 确认 `aiusage.chunbai.com/*` 由 Worker 接管，不被 Pages 占位入口抢走。
3. 确认 API health 返回 D1 canonical store。
4. 执行线上 smoke。

## Smoke Checklist

不要用 `curl -I` / `HEAD` 判断本 Worker 是否正常。线上 smoke 使用真实 `GET`：

- 默认 `curl -D - -o /dev/null`，只看状态码和关键 header。
- 如果本机 DNS、代理或 VPN 行为可疑，临时加 `--resolve aiusage.chunbai.com:443:<Cloudflare IP>` 对比。
- 业务 token 和 session cookie 只从运维目录安全读取，不输出。

未登录 /static/* 预期可以是 401；这不代表 Worker route 失败。带 session cookie 后 /static/dashboard.js 和 /static/dashboard.css 必须是 200。

```bash
curl -sS --max-time 12 -D - -o /dev/null \
  "https://aiusage.chunbai.com/"
curl -sS --max-time 12 -D - -o /dev/null \
  "https://aiusage.chunbai.com/static/dashboard.js"
curl -sS --max-time 12 -D - -o /dev/null \
  "https://aiusage.chunbai.com/static/dashboard.css"
curl -sS --max-time 12 -D - -o /dev/null \
  "https://aiusage.chunbai.com/api/mobile/summary?period=all"
```

认证路径需由运维 Agent 使用可用的安全 token 验证，但不要在输出中展示 token：

- `/login` 能写入 session cookie 并跳到 `/dashboard`。
- 登录后 `/api/summary` 返回 dashboard 数据。
- 带 session cookie 后 `/static/dashboard.js` 和 `/static/dashboard.css` 返回 200。
- `/ingest` 或 `/ingest-limits` 完成一次真实 POST smoke。

## 回报格式

```text
Worker 部署：
Route 读回：
Native Worker：
D1：
/ smoke：
/static smoke：
/login smoke：
/api/mobile/summary smoke：
/ingest 或 /ingest-limits smoke：
阻塞点：
```
