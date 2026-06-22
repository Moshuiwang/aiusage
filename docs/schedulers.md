# AI Usage Device Schedulers

本文档介绍了各平台终端设备（macOS、Linux、Windows）如何在其 OS 用户上下文中配置定时推送任务，实现数据静默自动 Push，避免汇聚端通过 **SSH** 主动抓取。

同时，我们强烈建议在部署前使用 **dry-run** 模式进行配置校验。

---

## 1. 定时任务启动命令基线

各平台定时调度底层调用的 Python 推送命令为：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect \
  --config config/sources.local.json \
  --output data/latest.json \
  --sqlite data/usage.sqlite
```

V2 HTTP push 部署应使用终端侧 pusher 命令：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli push \
  --config config/sources.local.json \
  --lock-file /tmp/ai-usage-pusher.lock
```

> [!IMPORTANT]
> - **绝对不要包含真实 Token**：在定时任务配置文件中，鉴权 Token 应该通过本机环境变量读取，或者写入本地忽略提交的 `sources.local.json` 配置文件中。
- **用户隔离**：命令必须在当前 OS 用户本人的上下文运行，不得使用 `root` 或高权限用户代跑，以保障 `ccusage` 数据读取的安全隔离性。

---

## 2. macOS 平台定时任务配置 (`launchd`)

macOS 平台推荐使用系统自带的 `launchd` 配置定时任务。

### 2.1 配置文件

在 `~/Library/LaunchAgents/com.chunbai.aiusage.pusher.plist` 中创建以下文件：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.chunbai.aiusage.pusher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>ai_usage_widget.cli</string>
        <string>push</string>
        <string>--config</string>
        <string>/Users/<user>/Documents/ai-usage-widget/config/sources.local.json</string>
        <string>--lock-file</string>
        <string>/Users/<user>/Library/Caches/ai_usage_pusher.lock</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>/Users/<user>/Documents/ai-usage-widget/src</string>
        <key>AI_USAGE_INGEST_TOKEN</key>
        <string>admin-secret-token</string>
    </dict>
    <key>StartInterval</key>
    <integer>1800</integer> <!-- 每30分钟执行一次 -->
    <key>StandardOutPath</key>
    <string>/Users/<user>/Library/Logs/ai_usage_pusher.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/<user>/Library/Logs/ai_usage_pusher.stderr.log</string>
</dict>
</plist>
```

### 2.2 启动与管理
```bash
# 注册并启动定时推送服务
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.chunbai.aiusage.pusher.plist

# 立即执行一次 (用于验证配置，等同于 dry-run 测试)
launchctl kickstart -k gui/$(id -u)/com.chunbai.aiusage.pusher
```

### 2.3 Official Limits Collector

limits provider 必须在拥有对应 Codex / Claude credential 的当前 macOS 用户上下文运行。不要用 `root` 或其他用户代跑，否则 CLI/keychain/app-server socket 可能不可见。

如果只想写入本机 SQLite，可以继续使用 `collect-limits`。如果要持续推送到生产，应使用 TP-V2-042 提供的 `install-limits-scheduler`，它会生成本机 LaunchAgent、runner 脚本、日志目录和 0600 token env 文件。

部署前先 dry-run，确认不会写文件且输出不包含 token：

```bash
cd /Users/<user>/Documents/ai-usage-widget
PYTHONPATH=src AI_USAGE_INGEST_TOKEN=<token-from-production> \
python3 -m ai_usage_widget.cli install-limits-scheduler \
  --url https://aiusage.chunbai.com/ingest-limits \
  --dry-run
```

正式安装：

```bash
cd /Users/<user>/Documents/ai-usage-widget
PYTHONPATH=src AI_USAGE_INGEST_TOKEN=<token-from-production> \
python3 -m ai_usage_widget.cli install-limits-scheduler \
  --url https://aiusage.chunbai.com/ingest-limits
```

默认生成：

- `~/Library/Application Support/ai-usage-widget/limits-push.env`：本机 token env 文件，权限 `0600`。
- `~/Library/Application Support/ai-usage-widget/limits-push.sh`：runner 脚本，不含 token。
- `~/Library/LaunchAgents/com.chunbai.aiusage.limits-push.plist`：LaunchAgent，不含 token。
- `~/Library/Logs/ai-usage-widget/limits-push.stdout.log`
- `~/Library/Logs/ai-usage-widget/limits-push.stderr.log`
- `~/Library/Caches/ai-usage-widget/limits-push.lock`

激活并立即运行一次：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.chunbai.aiusage.limits-push.plist
launchctl kickstart -k gui/$(id -u)/com.chunbai.aiusage.limits-push
```

查看状态：

```bash
launchctl print gui/$(id -u)/com.chunbai.aiusage.limits-push
tail -n 50 ~/Library/Logs/ai-usage-widget/limits-push.stdout.log
tail -n 50 ~/Library/Logs/ai-usage-widget/limits-push.stderr.log
```

如果只需要本机 collector 模板，launchd 示例仍然如下：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.chunbai.aiusage.limits</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>ai_usage_widget.cli</string>
        <string>collect-limits</string>
        <string>--limits-config</string>
        <string>/Users/<user>/Documents/ai-usage-widget/config/limits.local.json</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>/Users/<user>/Documents/ai-usage-widget/src</string>
    </dict>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardOutPath</key>
    <string>/Users/<user>/Library/Logs/ai_usage_limits.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/<user>/Library/Logs/ai_usage_limits.stderr.log</string>
</dict>
</plist>
```

---

## 3. Linux 平台定时任务配置 (`systemd` timer)

Linux 服务器（如 Ubuntu/CentOS）推荐使用 **systemd** 定时器。

### 3.1 Service 配置文件
在 `~/.config/systemd/user/ai-usage-pusher.service` 中配置：

```ini
[Unit]
Description=AI Usage Pusher Service
After=network.target

[Service]
Type=oneshot
WorkingDirectory=%h/ai-usage-widget
Environment=PYTHONPATH=%h/ai-usage-widget/src
Environment=AI_USAGE_INGEST_TOKEN="admin-secret-token"
ExecStart=/usr/bin/python3 -m ai_usage_widget.cli push --config %h/ai-usage-widget/config/sources.local.json --lock-file %h/.cache/ai_usage_pusher.lock
StandardOutput=append:%h/.local/state/ai_usage_pusher.log
StandardError=append:%h/.local/state/ai_usage_pusher.err
```

### 3.2 Timer 配置文件
在 `~/.config/systemd/user/ai-usage-pusher.timer` 中配置：

```ini
[Unit]
Description=Run AI Usage Pusher every 30 minutes

[Timer]
OnCalendar=*:0/30
Persistent=true

[Install]
WantedBy=timers.target
```

### 3.3 激活服务
```bash
# 在用户级别重新加载 systemd 配置
systemctl --user daemon-reload
systemctl --user enable --now ai-usage-pusher.timer

# 测试单次运行 (dry-run 校验)
systemctl --user start ai-usage-pusher.service
```

### 3.4 Official Limits Collector

limits provider 应使用用户级 systemd timer，并在拥有 Codex / Claude credential 的 OS 用户下运行。不要用 `root` 代跑普通用户的 Claude/Codex credential。

部署前先 dry-run：

```bash
PYTHONPATH=%h/ai-usage-widget/src \
python3 -m ai_usage_widget.cli collect-limits \
  --limits-config %h/ai-usage-widget/config/limits.local.json \
  --dry-run
```

Service：

```ini
# ~/.config/systemd/user/ai-usage-limits.service
[Unit]
Description=AI Usage Official Limits Collector
After=network.target

[Service]
Type=oneshot
WorkingDirectory=%h/ai-usage-widget
Environment=PYTHONPATH=%h/ai-usage-widget/src
ExecStart=/usr/bin/python3 -m ai_usage_widget.cli collect-limits --limits-config %h/ai-usage-widget/config/limits.local.json
StandardOutput=append:%h/.local/state/ai_usage_limits.log
StandardError=append:%h/.local/state/ai_usage_limits.err
```

Timer：

```ini
# ~/.config/systemd/user/ai-usage-limits.timer
[Unit]
Description=Run AI Usage Official Limits Collector every 30 minutes

[Timer]
OnCalendar=*:0/30
Persistent=true

[Install]
WantedBy=timers.target
```

激活：

```bash
systemctl --user daemon-reload
systemctl --user enable --now ai-usage-limits.timer
systemctl --user start ai-usage-limits.service
```

---

## 4. Windows 平台定时任务配置 (`Task Scheduler`)

Windows 平台推荐使用任务计划程序（**Task Scheduler**）来定时触发推送脚本。

### 4.1 命令行单次测试 (Dry-Run)
在 PowerShell 终端以当前用户上下文执行：
```powershell
$env:PYTHONPATH="C:\path\to\ai-usage-widget\src"
$env:AI_USAGE_INGEST_TOKEN="admin-secret-token"
python.exe -m ai_usage_widget.cli push --config C:\path\to\ai-usage-widget\config\sources.local.json --lock-file C:\Users\<user>\AppData\Local\Temp\ai_usage_pusher.lock
```

### 4.2 配置步骤
1. 打开 `taskschd.msc`（任务计划程序）。
2. 点击 **创建基本任务**，命名为 `AIUsagePusher`。
3. 触发器选择：**每天**，并在高级设置中配置为“每隔 30 分钟重复一次”。
4. 操作选择：**启动程序**：
   - **程序/脚本**: `python.exe`
   - **添加参数**: `-m ai_usage_widget.cli push --config C:\path\to\ai-usage-widget\config\sources.local.json --lock-file C:\Users\<user>\AppData\Local\Temp\ai_usage_pusher.lock`
   - **起始于**: `C:\path\to\ai-usage-widget`
5. 在条件选项卡中，确保勾选“只有在以下网络连接可用时才启动：任何连接”，以防止无网络时报错。
6. 日志将输出至系统事件查看器，也可以在启动参数中重定向输出。

### 4.3 Official Limits Collector

在拥有 Claude / Codex 登录态的 Windows 用户上下文执行 dry-run：

```powershell
$env:PYTHONPATH="C:\path\to\ai-usage-widget\src"
python.exe -m ai_usage_widget.cli collect-limits `
  --limits-config C:\path\to\ai-usage-widget\config\limits.local.json `
  --dry-run
```

Task Scheduler 操作配置：

- **程序/脚本**: `python.exe`
- **添加参数**: `-m ai_usage_widget.cli collect-limits --limits-config C:\path\to\ai-usage-widget\config\limits.local.json`
- **起始于**: `C:\path\to\ai-usage-widget`
