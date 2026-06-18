# macOS Client

目标用户体验：

- macOS 优先做菜单栏或轻量桌面入口。
- 用户快速看到今日用量、可信额度状态、采集健康，并能打开 Web dashboard。
- 不把 macOS Widget 作为新的产品主线。

边界：

- macOS client 不执行 `ccusage`，采集仍由本机 pusher 负责。
- macOS client 不读取 SQLite。
- 既有 `widget/macos` 只保留为 legacy 参考。

## 当前实现

`clients/macos` 现在提供 SwiftUI/AppKit 菜单栏 App：

- 菜单栏常驻显示 `AI <当前周期 token>`。
- 点击后可切换今天、本周、本月、全部。
- 弹窗内展示 token 汇总、趋势、可信额度、采集来源和机器/账户/Agent/模型/日期明细。
- 默认 10 分钟低频刷新；用户打开弹窗或点击刷新会立即读取一次。
- 只请求 `/api/mobile/summary`，不执行采集、不读 SQLite、不读 legacy `data/latest.json`。

## 安装

```bash
cd /Users/wangzhipeng/Documents/ai-usage-widget
python3 clients/macos/scripts/install_menu_bar_app.py \
  --server-url https://vpn2.chunbai.com:8443
```

安装脚本会构建并安装到：

```text
/Applications/AI Usage Menu Bar.app
```

退出后可从 macOS「应用程序」、Spotlight 或 Launchpad 重新打开 `AI Usage Menu Bar`。

运行时配置和缓存固定在：

```text
~/Library/Application Support/ai-usage-widget/macos-menu-bar/
```

这条路径避开 `~/Documents`，所以菜单栏 App 运行时不会因为访问项目目录反复弹出“文稿”权限确认。

Token 默认从 `AI_USAGE_INGEST_TOKEN` 读取，只写到用户本机的 `config.json`，不会写入仓库。
