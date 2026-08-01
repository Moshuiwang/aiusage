# TP-V2-093 Native Web Surface（切流前必备）

Status: done
Milestone: Cloudflare 迁移 M4/M5 前置（见 `docs/architecture/cloudflare-migration-objective.md`）
依赖：TP-V2-088（只读 API）、TP-V2-089（写入）

## Goal

给 Native worker 补齐切流所需的**完整对外面**，使它能 1:1 取代当前 `aiusage-api` 代理服务的全部路径：`/login`（签发与 Python **逐字节一致**的 session cookie）、`GET /` 与 `/dashboard`（HTML）、`/static/*`（dashboard 资源）、`/api/health`，以及 read API 的 cookie 鉴权。

## Context

M2 只做 read API，M3 只做 ingest。切流（M5）要求 Native 服务现在代理的所有路径。**登录态连续性**是关键：cookie 派生必须与 `server.py` 完全一致（`hmac.sha256` over `"ai-usage-dashboard-session-v1"`，key=session secret），否则切流后所有已登录用户被登出。

## Scope

- `/login`：表单或 JSON token → 验证 → `Set-Cookie`，属性与 `server.py` `_session_cookie_header` 一致（`HttpOnly; Secure; SameSite=Lax; Max-Age=2592000; Path=/`），cookie 值与 `_session_cookie_value` 逐字节一致。
- session cookie 鉴权：read API（/api/summary、/api/mobile/summary）、/api/health、/、/dashboard、/static/* 接受同款 cookie。
- `GET /`、`/dashboard`：未登录返回登录页，登录返回 dashboard HTML。
- `/static/*`：服务 `dashboard.css`、`dashboard.js`、`index.html`、`login.html`，内容与 `src/ai_usage_widget/static` 一致（建议 worker static assets 或打包内嵌；R2 亦可——给出建议）。
- `/api/health`：保持 M0 health 合同 shape；原 health 看本地文件 size/mtime，Native 改看 D1/KV 元数据，易变字段掩码。
- 错误模型与安全 headers 与 Python 一致。

## Out of Scope

- 不部署、不切流、不改 live proxy `aiusage-api-worker.js` 或根 `wrangler.toml`、不动 Python `src/`、不 `git add`/`commit`。

## Red Test

先写：cookie-parity（Native cookie 值 == Python `_session_cookie_value` 同 secret）、login 流程、static、health 合同测试，跑红。

## Acceptance Criteria

- session cookie 值对同一 secret 与 Python **逐字节一致**（登录态可跨切流保留）。
- `/login` Set-Cookie 属性与 Python 一致。
- `/`、`/dashboard`、`/static/*`、`/api/health` 行为与 M0 合同一致（health 易变字段掩码）。
- read API 接受 cookie 鉴权。
- `pnpm run cf:native:test` 全绿；`PYTHONPATH=src python3 -m unittest discover -s tests` 不回归。

## Verification

测试输出。

## Handoff

报告：实现、cookie-parity 结果、static 服务方式建议（assets vs R2）、对 staging 部署的建议。不要 `git add`/`commit`。
