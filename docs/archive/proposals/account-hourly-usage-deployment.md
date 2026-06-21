# Deployment: Account Hourly Usage

## 目标

把“按 AI 账号、机器、机器登录用户统计小时用量”上线到现有个人 HTTP push 架构。

上线后用户看到的是：

- 今日总用量继续稳定显示，不被新账号归因口径影响。
- 新增账号小时分析区块，可以按 AI 账号、机器、OS 用户、agent 看用量。
- 某个采集器没上传或账号未知时，页面能显示状态，而不是把缺失误认为 0。

## 上线原则

- 服务器先兼容上线，终端逐台逐用户接入。
- 不直接读取其他 OS 用户的 `~/.claude` 或 `~/.codex`。
- 不上传 token、cookie、原始日志路径或原始日志内容。
- `ccusage daily` baseline 继续保护主总数。
- 新的 `usage_hourly_facts` 先作为账号归因分析，不直接替代主 total。

## 部署顺序

### 1. 服务端上线

目标机器：`vpn2.chunbai.com`

服务目录：`/home/ubuntu/ai-usage-widget`

上线动作：

1. 备份当前 SQLite。
2. 更新代码。
3. 重启 HTTP ingest 服务。
4. 让服务自动创建新表：
   - `machines`
   - `os_identities`
   - `ai_accounts`
   - `usage_hourly_facts`
   - `usage_hourly_models`
5. 验证老接口仍可用：
   - `/api/health`
   - `/api/summary`
   - `/api/mobile/summary`
6. 验证 summary 中出现 `account_hourly`，即使还没有数据也返回空结构。

用户体验验收：

- Dashboard 原总数不变。
- iPhone App / Widget 不崩。
- 新账号小时数据未接入前，账号分析为空，不影响主页面。

### 2. 本机 Mac 先接入

先只接当前 Mac 的当前登录用户。

配置文件仍使用本机私有配置，不提交仓库。

示例配置新增：

```json
{
  "source_id": "macbook-wang",
  "server_url": "https://vpn2.chunbai.com:8443/ingest",
  "timezone": "Asia/Shanghai",
  "platform": "darwin",
  "host": "MacBook-Pro.local",
  "machine": "MacBook Pro",
  "os_user": "wangzhipeng",
  "token_env": "AI_USAGE_INGEST_TOKEN",
  "ai_accounts": {
    "codex": {
      "provider": "openai",
      "account_id": "startimessocietegn@gmail.com",
      "label": "startimessocietegn@gmail.com",
      "display_name": "StarTimes",
      "attribution_confidence": "account_observed_usage_inferred",
      "evidence_source": "device_config"
    }
  }
}
```

说明：

- 第一版只有配置里明确写出的账号才上传账号小时事实。
- 没配置账号时，终端仍上传旧 daily/hourly 数据，不上传账号归因事实。
- 后续自动读取当前 Codex / Claude 登录账号，需要单独验证后再开启。

本机 smoke：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli push --config config/sources.local.json --lock-file /tmp/ai-usage-pusher.lock
```

用户体验验收：

- 服务器收到本机上报。
- `/api/summary` 里 `account_hourly.by_ai_account` 出现配置的账号。
- 主 `summary.total_tokens` 不因为账号小时事实重复增加。

### 3. 每台机器、每个 OS 用户接入

每个需要统计的 OS 用户都要在自己的账户上下文部署一次。

例子：

- Mac `wangzhipeng` 用户部署一份。
- Linux `ubuntu` 用户部署一份。
- Linux `wang` 用户如果也使用 Claude/Codex，也部署一份。

不要做：

- 不要用 root 统一扫描所有用户目录。
- 不要让 `wang` 读取 `/home/ubuntu`。
- 不要从 Mac 同步远程 `~/.claude` / `~/.codex` 原始日志。

### 4. 定时任务

macOS 使用 LaunchAgent：

- 每小时执行一次 push。
- 使用 lock file 防止并发。
- token 从环境或 launchd 安全配置注入。

Linux 使用 user-level systemd timer：

- 每个 OS 用户各自安装自己的 timer。
- 不使用系统级 root timer 代替用户任务。

推荐频率：

- 初期每小时一次。
- 验证稳定后仍保持每小时，不需要高频扫描。

### 5. 验证清单

服务端验证：

- `/api/health` 正常。
- `/api/summary` 正常。
- `/api/mobile/summary` 正常。
- SQLite 中有 `usage_hourly_facts`。
- `account_hourly.total_tokens` 只反映账号小时事实，不覆盖 daily baseline。

终端验证：

- 当前 OS 用户能执行 push。
- 上传 payload 不包含 `.codex` / `.claude` 路径。
- 配置了账号时，payload 包含 `usage_hourly_facts`。
- 未配置账号时，payload 不包含账号事实，但 daily baseline 仍上传。

用户体验验证：

- Dashboard 主总数稳定。
- 账号维度出现后能看出“哪个 AI 账号、哪台机器、哪个 OS 用户”。
- 账号未知时显示 unknown 或空分析，不误标到其他账号。

### 6. 回滚

如果服务端异常：

1. 停止服务。
2. 回到上一版代码。
3. 恢复备份 SQLite，或保留新表但旧代码忽略它们。
4. 重启服务。

如果终端异常：

1. 禁用对应用户的定时任务。
2. 保留服务器。
3. 等修复后单用户 smoke 再恢复。

这个设计下，新表和新字段是向后兼容的；回滚终端采集不会影响已有 Dashboard / iPhone 主用量。

## 当前完成边界

已具备：

- `/ingest` 接收 `usage_hourly_facts`。
- SQLite 保存机器、OS 用户、AI 账号和小时事实。
- `/api/summary` 输出 `account_hourly`。
- pusher 在显式配置 Codex 账号时，把 Codex hourly 报告转换成账号小时事实。

未完成：

- 自动读取当前 Codex 登录账号并动态写入配置。
- 自动读取当前 Claude Code 登录账号并动态写入配置。
- Web Dashboard 展示 `account_hourly` 的新 UI。
- iPhone App 展示账号小时分析。
