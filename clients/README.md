# Clients

`clients/` 是用户可见展示端的目标目录。所有客户端都只读 server API、移动端 DTO 或派生快照，不执行采集、不执行 SSH、不直接读取 SQLite。

当前落地状态：

- `ios/`：目标落点是 iPhone App 和 iOS Widget；现有实现暂时仍在 `mobile/ios` 和 `mobile/ios-xcode`，迁移前不要直接移动，避免破坏 SwiftPM / Xcode 路径。
- `android/`：目标落点是 Android App 和 Android Widget，复用 `/api/mobile/summary`，不重新定义 usage / limits 口径。
- `macos/`：目标落点是菜单栏或轻量桌面入口，不再把 macOS Widget 作为新产品主线。
- `windows/`：目标落点是托盘或轻量桌面入口，完整体验优先打开 Web dashboard。
- `web/`：目标落点是 Web dashboard；现有生产静态资源暂时仍在 `src/ai_usage_widget/static`。

迁移规则：

- 新平台先在对应子目录写 README / task package / prototype，再进入实现。
- 现有代码迁移必须单独开任务包，先补路径或构建测试，再移动文件。
- 客户端共享的数据合同放在 `packages/client-contracts/`。
- 视觉 token 和跨端状态色放在 `packages/design-tokens/`。
