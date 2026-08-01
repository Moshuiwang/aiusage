---
name: verify
description: ai-usage 的验证入口与证据等级判定。在声称任务完成、汇报测试结果、或需要说明「验证到了哪一级」时使用；也用于判断某项验收是否本机不可完成、需要回 Mac 侧执行。
---

# 验证与证据

## 唯一验证入口

```bash
scripts/verify.sh                # 全量：Python 约 85s + Cloudflare Worker 约 180s
scripts/verify.sh --python-only  # 快速：只跑 Python 约 85s
```

不要手写测试命令，不要只跑单个测试文件就宣称通过。脚本会显式打印跳过项和原因。

单个用例调试可以直接用 `PYTHONPATH=src python3 -m unittest tests.test_x.TestY.test_z`，
但**收口汇报必须以 `verify.sh` 的结果为准**。

## 证据等级（汇报时必须写明当前级别）

| 级 | 含义 | 本机能达到？ |
| --- | --- | --- |
| 1 | 已完成分析 | ✅ |
| 2 | 已完成本地修改 | ✅ |
| 3 | 本地测试通过 | ✅ `verify.sh` 退出 0 |
| 4 | CI 或自动化检查通过 | ⚠️ 需 push 后看 GitHub Actions |
| 5 | 已部署到目标环境 | ❌ 需 Mac 侧 Ops Agent |
| 6 | 真实用户旅程验证通过 | ❌ 需真机 / 浏览器 |
| 7 | 已从来源系统回读确认 | ❌ 需生产凭据 |

**`verify.sh` 退出 0 只等于第 3 级。** 禁止用低一级证据宣称高一级完成。
文档、代码或 CI 证明的是能力存在，不自动证明真实环境已经生效。
尚未验证的层级必须在汇报里明确列出。

## 本机（Linux 开发机）不可验证的项

- iOS / macOS Swift 测试与构建：`swift test`、`xcodebuild`、`xcodegen`、模拟器、真机、Apple Watch
- 真实 Cloudflare 部署、Secrets、路由变更、线上 smoke（走 `/Users/wangzhipeng/Documents/ops` 的 Ops Agent）
- 真实 ingest 上报（无 `AI_USAGE_INGEST_TOKEN`）
- 真实 daily 采集（未安装 `ccusage`，无 `config/sources.local.json`）
- 外部 skill `ai-usage-fact-check`（仅 Mac 侧安装，对应 9 个 skipped 测试）

遇到这些：标注「需回 Mac 侧执行」并列为**验收缺口**，不要尝试复现，
也不要因为跑不了就判定为环境故障。本机完整事实见仓库根 `ENVIRONMENT.local.md`。

## 汇报格式

小型低风险任务用一两句说明结果、实际改动和未验证事项即可。
复杂、高风险或涉及外部副作用的任务用完整收口卡：

- **结果**：完成 / 部分完成 / 阻塞
- **用户现在能获得什么**
- **实际改动范围**（文件级）
- **当前证据等级**（1-7，以及是怎么得到的）
- **尚未验证或仍然未知的事项**
- **外部系统和生产状态**
- **回滚或恢复方式**
- **建议的下一步**

不要用「应该」「可能」「大概完成」代替事实；无法确认时明确写「未知」。
