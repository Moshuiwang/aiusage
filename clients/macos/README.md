# macOS Client

目标用户体验：

- macOS 优先做菜单栏或轻量桌面入口。
- 用户快速看到今日用量、可信额度状态、采集健康。
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
- 今天、本周、本月、全部各自保留本地缓存；切换周期时先显示缓存，再按需后台刷新。
- 默认 10 分钟低频刷新；右上角刷新按钮会强制读取线上数据。
- 只请求 `/api/mobile/summary`，不执行采集、不读 SQLite、不读 legacy `data/latest.json`。

## 一体化 App（2.1.0）

App 包含菜单栏与独立的本机采集进程（采集端 0.4.0），内置 Python 运行时。展示模型仍然只读服务端 summary，采集由独立进程完成。打开 App 后每半小时采集并批量上报用量与官方额度；「完全退出」停止 App 管理的采集，App 异常退出后采集进程也会终止。休眠期间不会轮询网络，唤醒后到期补采。采集失败按下次半小时重试；单个任务最多运行四分钟。

首次打开从「连接设置…」输入服务地址、访问令牌和本机来源标识。令牌只写入当前用户的私有配置文件。可在「⋯」菜单查看本机上报状态、立即采集、暂停采集和设置「登录时启动」。这些操作不需要手工编写 LaunchAgent 或 shell 脚本。官方额度依赖本机对应 Agent 的有效登录；读取失败不会伪装为可信额度。App 不安装 Agent 本体，也不跨用户读取原始日志。

## 构建与安装

构建机器需要 Swift 工具链和 Python；Python 的构建环境需安装 `PyInstaller==6.16.0`。PyInstaller 把运行时放入标准嵌套 helper App，安装后的用户不需要 Python、源码目录或这项构建依赖。打包方式参见 [PyInstaller 官方文档](https://pyinstaller.org/en/stable/operating-mode.html)。

```bash
python3 clients/macos/scripts/install_menu_bar_app.py \
  --server-url https://aiusage.chunbai.com --launch
```

构建完成前及采集 helper 缺失时拒绝覆盖已有 App。默认安装位置：

```text
/Applications/AI Usage Menu Bar.app
```

Mac mini 的 Command Line Tools 默认 macOS 27 SDK 缺 SwiftUI 宏插件时，可显式选择已安装的完整 SDK：

```bash
AI_USAGE_SWIFT_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
  python3 clients/macos/scripts/install_menu_bar_app.py --launch
```

`--collector-bundle` 可以传入预构建的 `AIUsageCollector.app`。`--import-existing-collector` 只导入当前用户既有 `AIUsageWidget/config/device.json` 及最新额度配置，保留 source_id、账户映射和 outbox 路径；已有新配置不会被覆盖。此参数不会自动开启采集或停用旧 LaunchAgent。已有后台任务迁入 App 时，必须先停旧任务，再启用 App 采集，确认用量与额度均上报成功后将旧 plist 移出 LaunchAgents 并保留备份；失败时恢复旧任务。不要同时保留两套调度。

运行时配置和缓存固定在：

```text
~/Library/Application Support/ai-usage-widget/macos-menu-bar/
```

这条路径避开 `~/Documents`，所以菜单栏 App 运行时不会因为访问项目目录反复弹出“文稿”权限确认。
周期缓存保存在该目录下的 `summaries/`，以周期和偏移量分别存放（如 `today-offset0.json`、`month-offset-1.json`）。旧版滚动周期缓存不再加载，跨北京时间午夜也会重新请求，避免把上一天的相对日期当成今天。

Popover 提供日、周、月三个入口。日可回看最近 7 天；周从周一开始，月按自然月，不能进入未来。日期以服务端返回为准。来源默认折叠，展开后显示 Claude / Codex，再展开可看模型；缺失数据明确标记。菜单栏数字始终显示今日用量。

Popover 使用系统背景材质（Liquid Glass 暂未实现，见 #155）；开启“降低透明度”或提高对比度时使用实色背景。

采集配置在该目录下的 `collector/`；连接配置和采集配置权限为 `600`，采集目录权限为 `700`。采集状态只保留成功/失败、退出码和更新时间，不保存 payload 或原始诊断。

Token 默认从 `AI_USAGE_INGEST_TOKEN` 读取，只写到用户本机的 `config.json`，不会写入仓库。

### 新机器授权与升级

新机器在连接设置中留空令牌可申请授权，由管理员在“管理设备申请…”核对配对码后批准，再选择“检查本机授权”启用采集。管理员凭据单独保存，旧共享令牌不能批准设备。

“检查 App 更新…”使用固定公钥验证签名发布，更新器独立运行，失败恢复旧 App，并保留用户配置与 outbox。生产启用顺序、Linux 命令和发布工具见 [设备授权与签名升级](../../docs/device-registration-and-upgrades.md)。正式公钥与发布地址尚未配置时不会下载或替换 App。
