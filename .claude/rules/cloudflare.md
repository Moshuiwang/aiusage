---
paths:
  - "cloudflare/**"
  - "wrangler.toml"
---

# Cloudflare 入口与运维边界

## 当前生产事实

- 生产入口 `https://aiusage.chunbai.com`，由 **Cloudflare Worker + D1** 承载。
  canonical store 是 **Cloudflare D1**（SQLite-compatible serverless SQL，不是 PostgreSQL）。
- 入口 Worker = `aiusage-api`（`cloudflare/native-worker/`，路由 `aiusage.chunbai.com/*`），
  直接读写 Cloudflare D1；不再经过 legacy proxy、VPN2 或 Pages。
- **VPN2 旧 Python 后端已下线**，不再参与读写链路。文档里仍写「回源 vpn2.chunbai.com:8443」的
  段落是历史内容，以 `cloudflare/native-worker/wrangler.toml` 和 Native 代码为准。
- 正式配置唯一入口是 `cloudflare/native-worker/wrangler.toml`，绑定生产 D1 `aiusage-prod-db` 和 R2 `aiusage-backups`，
  并声明每日维护与每月首日备份 Cron。生产不配置 `SHADOW_INGEST_URL` 或 Supabase 旁路密钥。

## 运维边界（本机不可执行）

真实 Cloudflare 账号操作——部署、设 Secrets、改路由、创建 D1 schema、线上 smoke——
**只能在 macOS 侧由 Ops Agent 执行**：

```
codex exec --cd /Users/wangzhipeng/Documents/ops --skip-git-repo-check "<Cloudflare 运维任务说明>"
```

凭据在该目录，**不读、不输出**任何密钥值。完整流程见 `cloudflare/OPERATIONS_HANDOFF.md`。

Linux 开发机没有该目录和凭据。遇到这类任务直接停下，标注「需回 Mac 侧执行」并列为验收缺口，
不要尝试用本目录的任何凭据替代 Ops。

## smoke 约定

- 用 `GET`（`curl -D - -o /dev/null`），**不要**用 `HEAD` / `curl -I`。
- 未登录访问 `/static/*` 返回 401 是预期行为（origin 把静态资源放在登录态后）。
- workers.dev 直连可能被本机 HTTPS 代理干扰，需要 `env -u HTTPS_PROXY -u http_proxy` 并带浏览器 UA。

## 测试

`npm run cf:native:test` 需要 **Node >= 22**。统一走 `scripts/verify.sh`，不要手写命令。
