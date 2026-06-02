# AI Usage Ingest Server Operations

本文档介绍了个人 HTTP 数据汇聚服务端（Ingest Server）的运行、配置、数据备份与安全边界设计。

## 1. 运行与启动

AI Usage Ingest Server 整合在命令行工具中。你可以使用以下命令在本地或远程服务器上启动它：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli server \
  --host 0.0.0.0 \
  --port 8000 \
  --db data/usage.sqlite \
  --latest data/latest.json \
  --timezone Asia/Shanghai
```

### 参数说明

- `--host`: 绑定网卡 IP（例如 `127.0.0.1` 仅限本地访问，`0.0.0.0` 允许外网访问）。
- `--port`: 监听端口（默认 `8000`）。
- `--db`: SQLite 数据库路径，即我们的 **SQLite** 存储，所有的用量事实都将保存在这里。
- `--latest`: 快照最新的 `latest.json` 导出路径。
- `--timezone`: 显式时区对齐参数（如 `Asia/Shanghai`）。

---

## 2. 鉴权与安全

### 2.1 Token 配置

Ingest 接口要求客户端提供 Bearer Token。你可以通过以下两种方式指定 Server 预期的 Token：

1. **命令行参数指定**：
   ```bash
   --token "your-secret-token-here"
   ```
2. **环境变量指定（推荐，即 token_env）**：
   ```bash
   export AI_USAGE_INGEST_TOKEN="your-secret-token-here"
   ```
3. **多 Token 轮换（推荐用于线上）**：
   ```bash
   export AI_USAGE_INGEST_TOKENS="ai-ubuntu:token-one,biai-wangzp:token-two"
   ```

`AI_USAGE_INGEST_TOKEN` 用于保持旧部署兼容；`AI_USAGE_INGEST_TOKENS` 用于新增或轮换终端 token。两者可以同时存在，服务端会接受任一 active token。`label` 只用于本地识别，不会返回给客户端。

> [!WARNING]
> **绝对不要**将真实 Token 提交到 Git 仓库，也不要提交 `config/sources.local.json` 等包含敏感鉴权信息的本地配置文件。

### 2.2 安全边界

- **非侵入式 Push 架构**：V2 重构废弃了原有的 SSH pull 模式。汇聚端**绝对不暴露 SSH**，也不主动登录远端机器。所有的用量事实由客户端在本地账户上下文运行 ccusage 后，通过 HTTPS/HTTP push 到 Ingest Server。
- **错误脱敏**：任何由于设备侧执行命令失败（如 `command_failed`）产生并记录到 SQLite 库中的报错日志在传输给 Ingest 服务端后，都会在入库及前端渲染时进行敏感路径（如 `/Users/username` 或 `/home/username`）和鉴权 Token 的正则表达式截断脱敏，防止通过报错信息暴露隐私。

---

## 3. SQLite 数据备份

所有的个人用量均保存在 SQLite 数据库中。你可以通过以下方式对数据进行备份（即 **backup**）：

### 3.1 离线物理备份
由于启用了 SQLite WAL（Write-Ahead Log）模式，在直接复制主 `.sqlite` 文件前，建议确保所有的写事务均已提交。最安全的办法是停止 Ingest 进程，然后将 `data/usage.sqlite` 以及同级目录下的 `data/usage.sqlite-wal`、`data/usage.sqlite-shm`（如果存在）一起复制备份：

```bash
# 备份到指定归档目录
cp data/usage.sqlite* /path/to/backup/dir/
```

### 3.2 在线热备份 (SQLite Online Backup)
推荐使用 CLI 内置备份命令。它会先执行 `PRAGMA integrity_check`，再通过 SQLite online backup API 生成一致性备份：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli backup \
  --db data/usage.sqlite \
  --backup-dir data/backups \
  --keep 14 \
  --max-total-mb 512
```

`--keep` 控制最多保留多少份备份，`--max-total-mb` 控制备份目录总量上限。线上小机器建议用更保守的 `--keep 7 --max-total-mb 128`。

也可以在进程运行期间使用 SQLite 命令行工具生成一致性备份：

```bash
sqlite3 data/usage.sqlite ".backup '/path/to/backup/dir/usage_backup_$(date +%F).sqlite'"
```

### 3.3 每日 systemd 备份 timer

服务端可加每日低频备份，避免高频 IO 和磁盘增长：

```ini
# /etc/systemd/system/ai-usage-backup.service
[Unit]
Description=AI Usage SQLite Backup

[Service]
Type=oneshot
User=root
WorkingDirectory=/home/ubuntu/ai-usage-widget
Environment=PYTHONPATH=/home/ubuntu/ai-usage-widget/src
ExecStart=/usr/bin/python3 -m ai_usage_widget.cli backup --db data/usage.sqlite --backup-dir data/backups --keep 7 --max-total-mb 128
```

```ini
# /etc/systemd/system/ai-usage-backup.timer
[Unit]
Description=Run AI Usage SQLite Backup daily

[Timer]
OnCalendar=*-*-* 03:20:00
Persistent=true

[Install]
WantedBy=timers.target
```

健康检查接口：

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/health
```

---

## 4. Systemd 服务配置 (Linux 远程部署)

对于远程 Linux 服务器（如 `vpn2.chunbai.com`），建议配置 systemd 守护进程来管理服务。当前 `vpn2` 以 `root` 账户部署在 `/home/ubuntu/ai-usage-widget`：

```ini
# /etc/systemd/system/ai-usage-server.service
[Unit]
Description=AI Usage Ingest and Web Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/ubuntu/ai-usage-widget
Environment=PYTHONPATH=/home/ubuntu/ai-usage-widget/src
Environment=AI_USAGE_INGEST_TOKEN="admin-secret-token"
Environment=AI_USAGE_INGEST_TOKENS="ai-ubuntu:token-one,biai-wangzp:token-two"
ExecStart=/usr/bin/python3 -m ai_usage_widget.cli server --host 0.0.0.0 --port 8000 --db data/usage.sqlite --latest data/latest.json
Restart=always

[Install]
WantedBy=multi-user.target
```

启动并激活服务：
```bash
sudo systemctl daemon-reload
sudo systemctl start ai-usage-server
sudo systemctl enable ai-usage-server
```
