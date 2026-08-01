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

> **模板由代码生成，不要手写。** `src/ai_usage_widget/deploy_units.py` 是 timer /
> service / calendar drop-in / launchd plist 的唯一生成入口，
> `tests/test_deploy_units.py` 会把仓库里已提交的模板与生成结果逐字节比对。
> 要改模板就改该模块，然后运行 `python3 -m ai_usage_widget.deploy_units --write`
> 重新生成（不带 `--write` 即漂移检查，有漂移退出 1）。
> 生成的 service 用 `EnvironmentFile=` 读取 token，**不再把 token 明文写进 unit**。

下面这份是历史手写示例，只用于理解字段含义；新设备请用生成器输出：

```ini
[Unit]
Description=AI Usage Pusher Service
After=network.target

[Service]
Type=oneshot
WorkingDirectory=%h/ai-usage-widget
Environment=PYTHONPATH=%h/ai-usage-widget/src
EnvironmentFile=%h/.config/ai-usage/ingest.env
ExecStart=/usr/bin/python3 -m ai_usage_widget.cli push --config %h/ai-usage-widget/config/sources.local.json --lock-file %h/.cache/ai_usage_pusher.lock
StandardOutput=append:%h/.local/state/ai_usage_pusher.log
StandardError=append:%h/.local/state/ai_usage_pusher.err
```

### 3.2 Timer 配置文件

> 新设备请直接用 §3.3 的 `install-collector`，它会按 `deploy_units.py` 生成并放好
> timer 与 service。本节只描述模板本身，供理解和排查用。

仓库中的 `deploy/systemd-user/ai-usage-pusher.timer` 是唯一模板（由
`deploy_units.py` 生成）。手工部署时复制到 `~/.config/systemd/user/ai-usage-pusher.timer`；
不要用现场 drop-in 改成 `OnUnitActiveSec`，也不要手写另一份定时口径。

BIAI 现有 system-level 多用户 timer 必须保留各自基础 unit 的 `Unit=` 映射，只把
`deploy/systemd/ai-usage-pusher-calendar.conf` 复制到各 timer 的 drop-in 目录。

```ini
[Unit]
Description=Run AI Usage Pusher every 30 minutes

[Timer]
OnCalendar=*:0/30
Persistent=true
AccuracySec=1min
RandomizedDelaySec=2min

[Install]
WantedBy=timers.target
```

### 3.3 安装 / 升级 / 回滚：`install-collector`

新设备不需要手工 copy 单元文件，也不需要手改 Python 路径。一个命令完成
版本化 release 安装 + 单元生成 + 启用：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli install-collector \
  --root /opt/ai-usage \
  --version 2026.08.01-1 \
  --revision "$(git rev-parse --short HEAD)" \
  --source-id linux-biai-wangzp \
  --device-config ./device.seed.json \
  --timer-scope user
```

行为约定：

- **幂等**：同一 `--version` + `--revision`连续执行两次，目录树、单元文件、
  符号链接全都不变，`changed` 第二次为 `false`，不会多出第二个 timer 或第二个来源。
- **不覆盖用户配置**：`--device-config` 只在 `<root>/config/device.json`
  尚不存在时用来生成；已存在就原样保留。种子配置会先过 `validate_device_config`。
- **版本号发布后不复用**：同 version 换 revision 会被直接拒绝。
- **激活失败自动回滚**：`daemon-reload` / `enable` 失败会退回上一个 release 与 timer，
  返回 `success=false`；只有回滚的 systemctl 也成功时 `rolled_back` 才是 `true`，
  否则给 `rollback_files_restored=true` + `rolled_back=false`。
- `--dry-run` 只回报计划，一个文件都不碰。
- token 的 env 文件目录按 `0700` 创建，设备配置按 `0600` 写。**本命令不写 token 值**，
  `<root>/secrets/ingest.env` 需要你自己按 `KEY=value` 放好。

回滚到上一个 release 与 timer（不修改用户配置）：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli rollback-collector --root /opt/ai-usage
```

默认沿用上一个 release 在 `release.json` 里记录的 `timer_scope`。

安装完成**不等于交付**：还需要真实上报一次并从 D1 回读、确认来源时间推进，
这一步需要生产 ingest token，不在本命令范围内。

如果坚持手工激活：

```bash
systemctl --user daemon-reload
systemctl --user enable --now ai-usage-pusher.timer
systemctl --user start ai-usage-pusher.service
```

验收 timer 时不能把 `active/running` 直接判成失败：`Persistent=true` 可能在重启后立即补跑。
此时先有界等待对应 service 完成，再要求 timer 为 `active/waiting`、下一次触发时间非空且在未来，
最后从 D1 做一次 source report 写后读。

### 3.3.1 离线诊断：`doctor`

部署或排障时先跑只读预检，它不写任何文件、不打印 token：

```bash
PYTHONPATH="$HOME/ai-usage-widget/src" \
python3 -m ai_usage_widget.cli doctor \
  --config "$HOME/ai-usage-widget/config/sources.local.json" \
  --release-dir "$HOME/ai-usage-widget" \
  --timer-unit ai-usage-pusher.timer \
  --timer-scope user
```

（`%h` 只在 systemd unit 文件里展开，shell 里是字面量，所以这里用 `$HOME`。）

**BIAI 那五个 system-level timer 必须加 `--timer-scope system`**，否则查的是用户级
manager，会把健康 timer 报成 `timer_without_future_trigger`。

**`--timer-unit` 不是可选装饰**：PYTHONPATH 检查读的是那个 timer 对应 service 里的
`Environment=PYTHONPATH=`（Issue #57 里出事故的正是这一份），不是你当前 shell 里的。
不给 `--timer-unit` 时该项显示为 `skipped`，不会给出通过结论。

输出是 JSON，`reason_code` 是机器可读结论，退出码按下一步动作分组：

| 退出码 | reason_code | 该做什么 |
| --- | --- | --- |
| 0 | `ok` | 预检通过 |
| 11 | `network_unreachable` | 连接根本没建立起来：查出网 / DNS / 代理，**不要轮换 token** |
| 12 | `entry_blocked_by_waf` | 放行采集端请求身份或来源 IP，**不要轮换 token** |
| 12 | `entry_redirected_to_portal` | 入口被门户 / IdP 302 接管，请求没到自家 origin；放行直连，**不要轮换 token** |
| 13 | `auth_token_invalid` | 换 ingest token |
| 14 | `device_identity_mismatch` / `timezone_mismatch` | 修设备身份或时区 |
| 15 | `runtime_release_unversioned` / `pythonpath_import_mismatch` | 修运行目录版本与 unit 里的 PYTHONPATH |
| 16 | `timer_without_future_trigger` | 修定时任务（先确认 scope 对不对） |
| 17 | `entry_route_unexpected` | **网络是通的**，但响应不是本产品的 `/api/health`（404/5xx/被接管的 200）：查域名解析目标、入口路由与 origin |
| 18 | `precheck_incomplete` | 有事实没采到（看 `unknown_checks`），结论不完整——这不是「通过」 |
| 1 | `doctor_failed` | doctor 自身跑不了（配置读不出来、`server_url` 缺失等），看 `detail` 字段 |

安全边界：探测**不跟随重定向**。CPython 默认跟随 3xx 且会把 `Authorization`
原样带到新主机，入口前挂 captive portal 或 Cloudflare Access 时一跳就会把生产
ingest token 交给第三方。doctor 只会向配置里的 origin 发一次带 token 的 GET。

**macOS 缺口**：doctor 只实现了 systemd 的 timer 检查。在 darwin 上给了
`--timer-unit` 会返回 `precheck_incomplete`（退出码 18）并提示需回 Mac 侧用
`launchctl print` 人工确认——launchd 分支尚未实现，本机（Linux）也无法验收。

离线重放（不访问网络，用于回归和演练），在仓库根执行：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli doctor \
  --environment-fixture tests/fixtures/deploy_doctor/case_entry_blocked_by_waf.json
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
