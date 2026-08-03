# Web Client

目标用户体验：

- Web dashboard 是完整驾驶舱。
- 用户在浏览器查看所有机器、OS 用户、agent、source health、趋势和可信额度状态。

当前实现仍保留在：

- `cloudflare/native-worker/static`（#74/PM-1 起归 Worker 管）

迁移到 `clients/web` 前必须单独开任务包，保证静态资源路由、登录、`/api/summary` 和生产部署不被破坏。
