---
name: verify
description: ai-usage 的验证入口与证据等级判定。在声称任务完成、汇报测试结果、或需要说明「验证到了哪一级」时使用；也用于判断某项验收是否本机不可完成、需要回 Mac 侧执行。
---

# 验证与证据

## 验证入口与收口口径（2026-08-03 起）

```bash
scripts/verify.sh                # 全量：Python 约 85s + Cloudflare Worker 约 6 分钟（本机实测）
scripts/verify.sh --python-only  # 快速：只跑 Python 约 85s
```

**收口口径：本地 targeted 绿 = 等级 3；全量套件交给 PR CI（等级 4）。**
PR 合并的唯一入口是 `scripts/merge_pr.sh`（四个 check 全 SUCCESS 才执行合并，
裸 `gh pr merge` 被 bash_guard 拦截；免费私有仓库无服务端 branch protection，
强制性在仓库内实现），所以全量不会被绕过——
它只是从「本机排队 6-8 分钟」挪到了「GitHub 并行 3 分钟」。
本地全量 `verify.sh` 仍可用，但只是可选复核，**不再是收口必要条件**
（2026-08-03 实测：一整轮交付里本地全量跑了约 10 次、共约 1 小时，
targeted 测试没抓到而全量抓到的问题为 0 个）。

targeted 的口径：Python 改动跑改动模块的测试文件或 `--python-only`；
Worker 改动跑改动相关的 test 文件
（`npx --prefix cloudflare/native-worker vitest run --config cloudflare/native-worker/vitest.config.ts <file>`）。
收口汇报必须写明跑了哪些 targeted、结果如何、全量由哪个 PR 的 CI 承担。

**两样东西永远在本地做,CI 替代不了**：TDD 的先红后绿；变异证据（破坏→变红→还原）。

**验证成本要匹配验证目的**（#68：前半程 3 次不必要的全量共浪费约 30 分钟）：
TDD 红阶段只跑目标测试文件（秒级），绿阶段跑相关模块。
全量 verify 运行期间**不要并发派 subagent**——CPU 竞争，#68 实测 5 个挂掉里 4 个在此时段。

## 证据等级（汇报时必须写明当前级别）

| 级 | 含义 | 本机能达到？ |
| --- | --- | --- |
| 1 | 已完成分析 | ✅ |
| 2 | 已完成本地修改 | ✅ |
| 3 | 本地测试通过 | ✅ targeted 测试绿（或 `verify.sh` 退出 0） |
| 4 | CI 或自动化检查通过 | ⚠️ 需 push 后看 GitHub Actions（PR 全量门禁在这一级） |
| 5 | 已部署到目标环境 | ❌ 需 Mac 侧 Ops Agent |
| 6 | 真实用户旅程验证通过 | ❌ 需真机 / 浏览器 |
| 7 | 已从来源系统回读确认 | ❌ 需生产凭据 |

**targeted 绿或 `verify.sh` 退出 0 都只等于第 3 级。** 禁止用低一级证据宣称高一级完成。
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
