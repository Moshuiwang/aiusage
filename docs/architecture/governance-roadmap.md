# Architecture Governance Roadmap

本文定义后续架构治理的分轮路线。它不是业务功能排期；每轮只处理一个风险面，完成后必须停止，等待用户确认。

## Completed Rounds

### Round 1: Server Service Boundary

目标：

- `server.py` 退回 HTTP adapter。
- `server_services.py` 承接业务编排。
- legacy SSH pull 标记。
- `architecture.md` 建立边界。
- `.gitignore` 防误提交。

状态：completed

### Round 2: Snapshot Read Model Helper Extraction

目标：

- 保持 `snapshot_builder.py` 是 summary read model owner。
- 拆出 period/filter/trend helper。
- 不改 API / JSON / schema / iOS。

状态：completed

### Round 3: iOS Runtime Configuration

目标：

- App 内配置 server URL/token。
- token 只走 Keychain。
- 移除明文 token fallback。
- Widget 配置共享明确延后。

状态：completed

### Round 4: Self-Hosted Server Trust Policy

目标：

- 复审当前非生产地址 fail closed 策略。
- 明确自托管 HTTPS 域名、EC2、内网 IP、localhost 的处理。
- 不降低 token 安全。
- 不让生产默认接受任意 HTTP / 裸 IP。
- 如果需要支持自托管，设计显式 trust policy。

状态：completed

### Round 5: Widget Configuration Sharing Design

目标：

- 设计 Widget 如何读取 server URL/token。
- 必须明确 App Group。
- 必须明确 Keychain access group。
- 不允许把 token 放进普通共享 UserDefaults。
- 如果无法安全实现，先只写设计文档，不写代码。

状态：completed

### Round 6: Snapshot Source Health Helper

目标：

- 从 `snapshot_builder.py` 拆 source health helper。
- 不改 usage 数字口径。
- 不改 summary JSON 合约。
- 补 source health fixture 测试。

状态：completed

### Round 7: Limits / Provider Runtime Cleanup

目标：

- 梳理 official quota / observed usage / local daily usage。
- 防止从 `ccusage daily` / `ccusage blocks` 推断官方 quota。
- provider missing/failure/observed 状态更清楚。

状态：completed

### Round 8: Directory And Document Governance

目标：

- 收敛架构、数据库、接口和项目地图入口。
- 归档已弃用路线、已完成任务包、历史设计稿和 review。
- 不改产品代码、API、SQLite schema 或客户端物理目录。
- 让 AI Agent 默认读取更少、更准的当前事实源。

状态：completed

## Upcoming Rounds

当前路线图内治理轮次已完成。后续如要继续治理，必须新建独立任务包和新轮次，不得混入已完成轮次。

## Subagent Workflow

每轮执行时，主 agent 必须使用以下 subagent 分工。subagent 可以并行做只读探索和复审，但实现型 subagent 每轮只能有一个主执行者，避免多 agent 同时改同一文件。

### explorer

- 只读。
- 读取相关文件。
- 输出 baseline、风险、允许修改文件建议。
- 不改代码。

### implementer

- 只修改本轮允许范围。
- 先补 characterization tests。
- 再做最小实现。
- 不跨轮修改。

### reviewer

- 只读。
- 检查 diff。
- 检查是否改 API / schema / JSON / 安全边界。
- 检查是否混入其他轮次。
- 输出必须修复和建议修复。

### tester

- 运行测试。
- 分析失败。
- 不为了通过测试擅自放宽测试。
- 输出测试结果。

主 agent 负责整合结果，不得让 subagent 自动进入下一轮。

如果当前 Codex custom agents 不可用，则按以上角色用自然语言分配 read-only review/tester subagents；仍遵守同样 stop gate。

## Per-Round Command Template

每轮开始：

```bash
git status --short
git diff --stat
```

每轮结束：

```bash
git diff --check
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

如果涉及 iOS：

```bash
cd mobile/ios && swift test
```

如果涉及 Xcode App：

使用项目已有 xcodebuild 命令，不要发明 scheme。

## Final Report Template

每轮必须输出：

1. 本轮目标
2. subagent 分工和结论
3. 修改文件
4. 行为不变保证
5. 安全边界
6. 测试结果
7. 未跟踪文件 / 用户 WIP
8. 剩余风险
9. 是否建议 commit
10. 下一轮建议
