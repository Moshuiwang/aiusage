# Windows Client

目标用户体验：

- Windows 优先做托盘或轻量桌面入口。
- 完整 dashboard 继续通过 Web 打开。
- 本地采集由 Windows pusher / Task Scheduler 负责，展示端只读 API。

边界：

- Windows client 不直接解析本机 usage 原始日志。
- 不重新计算 usage / limits / source health。
- 如果需要离线状态，先由 server 或 pusher 生成结构化状态，再展示。
