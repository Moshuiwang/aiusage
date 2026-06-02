# Project Handoff: AI Usage Observability V2

此文档为 V2 架构开发完毕后的交接文档，整理了后续部署任务与多终端安装说明，并提供后续 Agent 可直接执行的步骤指引。

## 1. 当前已完成工作 (截至 2026-06-01)
- [x] **HTTP Ingest 接收端**：在 [server.py](file:///Users/wangzhipeng/Documents/ai-usage-widget/src/ai_usage_widget/server.py) 实现 Ingest + Token 鉴权 + 幂等去重入库。
- [x] **暗黑极客风 Web Dashboard**：在 [static/index.html](file:///Users/wangzhipeng/Documents/ai-usage-widget/src/ai_usage_widget/static/index.html) 实现美观自适应的前端看板，完美包含在线/离线/未上报/失败状态渲染。
- [x] **后端与前端双重脱敏**：实现对设备报错日志（`error_message`）的敏感路径和 Token 脱敏。
- [x] **CLI 命令增强**：在 [cli.py](file:///Users/wangzhipeng/Documents/ai-usage-widget/src/ai_usage_widget/cli.py) 增加了 `server` 子命令。
- [x] **macOS Widget 兼容性改造**：Swift Core 源码已经支持 V2 `error_message` 解码映射，本地编译通过。
- [x] **测试覆盖**：36个 Python 单元测试和 Swift 测试全部通过。

有关开发详情，请参阅 [walkthrough.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/walkthrough.md) (由原 conversation-id 目录拷贝或生成)。

---

## 2. 后续未完成任务

### 2.1 任务一：远程服务器 Ingest Server 部署
- **目标服务器**：`vpn2.chunbai.com`，端口 `8000` 已放行。
- **采集端示例**：`ai.chunbai.com` 是 usage 采集端，不运行 Ingest Server。
- **部署步骤**：
  1. 将 Mac 本地代码库（`/Users/wangzhipeng/Documents/ai-usage-widget`）同步至远程服务器的 `/home/ubuntu/ai-usage-widget`。
  2. 在远程服务器上运行 Ingest Server，监听 `0.0.0.0:8000`，加载 `data/usage.sqlite` 作为数据存储。
  3. 配置 `systemd` user 级或 system 级服务实现开机自启（配置参考 [operations.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/operations.md)）。

### 2.2 任务二：多终端客户端定时 Pusher 注册
- **目标终端**：`mac-local` (当前 Mac)、`linux-server-1` (远程 Linux) 等。
- **部署步骤**：
  1. 在每个终端上安装 `ccusage`。
  2. 分别为各个终端配置 `sources.local.json`，将 `server_url` 设置为 `http://vpn2.chunbai.com:8000/ingest`，并配置相应的 Token 鉴权。
  3. 按照 [schedulers.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/schedulers.md) 中的平台配置（macOS 的 `launchd`，Linux 的 `systemd` timer，Windows 的 `Task Scheduler`）注册定时自动推送任务。
  4. 触发 `dry-run` 验证上报状态。
