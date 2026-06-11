# Android Client

目标用户体验：

- Android App 复用 iPhone 的移动信息架构。
- Android Widget 只展示今日用量、可信额度窗口、采集健康和最近更新时间。
- Android 不重新聚合 token、limits 或 source health。

数据入口：

- 优先消费 `/api/mobile/summary`。
- 如果字段不够，先扩展后端 mobile summary DTO，再改 Android UI。
