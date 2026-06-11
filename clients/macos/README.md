# macOS Client

目标用户体验：

- macOS 优先做菜单栏或轻量桌面入口。
- 用户快速看到今日用量、可信额度状态、采集健康，并能打开 Web dashboard。
- 不把 macOS Widget 作为新的产品主线。

边界：

- macOS client 不执行 `ccusage`，采集仍由本机 pusher 负责。
- macOS client 不读取 SQLite。
- 既有 `widget/macos` 只保留为 legacy 参考。
