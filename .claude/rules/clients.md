---
paths:
  - "mobile/**"
  - "clients/**"
  - "widget/**"
  - "packages/**"
  - "cloudflare/native-worker/static/**"
---

# 客户端目录现状（迁移期，勿擅自搬）

真实代码暂留原位，**不要为了「目录好看」移动文件**：

| 内容 | 当前位置 | 目标落点 |
| --- | --- | --- |
| iOS App / Widget | `mobile/ios`、`mobile/ios-xcode` | `clients/ios` |
| Web dashboard 静态资源 | `cloudflare/native-worker/static`（#74/PM-1 起归 Worker 管） | `clients/web` |
| macOS 菜单栏 | `clients/macos` | `clients/macos` |
| legacy macOS Widget | `widget/macos`、`widget/macos-xcode` | 仅历史兼容，**非后续主线** |

`clients/`、`packages/` 是目标落点与跨端合同 / 设计 token 区。
物理搬迁 iOS 或 Web 文件必须**单独开任务包**，并先补构建 / 路由验证。

## 展示层硬规则

- 客户端只读：不执行 `ccusage` / SSH / provider，不直接读 SQLite 私表重算口径，
  不在平台侧重新聚合 usage / limits / source health。
- Android、macOS、Windows 一律复用 `/api/mobile/summary` 合同，不在平台侧另算口径。
- macOS Widget 已退出产品路线，不要把它当成后续交付目标。

## 本机能力边界

`swift test`、`xcodebuild`、`xcodegen`、模拟器、真机、Apple Watch **在本 Linux 机上全部不可用**。
涉及这些的验收一律标注「需回 Mac 侧执行」，不要用「代码已写完」或「测试已通过」代替设备验收。
iPhone / Watch 交付不能只以 build、预检或安装成功为完成，必须有用户可见启动和非空真实数据证据。
