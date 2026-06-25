# TP-V2-098 Fact Check Board and Mac/D1 Accuracy

Version: V2
ID: TP-V2-098
Status: ready
Type: implementation
Depends on: none
Parallel with: TP-V2-097

## Goal

把定时核查结果变成可信、不过期、可行动的产品状态面板：自动更新 `docs/usage-fact-check-board.md`，补齐 D1 today tokens 证据，修正 Mac current collection 的 today tokens 口径，并降低 Mac 菜单栏缓存滞后对用户判断的误导。

## Context

最近事实核查发现：

- `docs/usage-fact-check-board.md` 停在 `2026-06-24 19:35 CST`，但手动核查已拿到 `2026-06-25 06:17 CST` 的新基线，说明定时核查没有可靠落板。
- Cloudflare 主站 API、D1 和 Mac 当前额度窗口可以对齐，但 helper 没有取 D1 层 today tokens。
- Mac current collection 是额度窗口采集源，不负责 today tokens；核查表把它写成“不完整”会误导用户以为 Mac 本机漏采 token。
- Mac 菜单栏缓存可能比主站 API 慢一拍，甚至短暂缺少已翻窗后的有效额度窗口；用户需要看到明确的缓存时间和差异原因。

本任务是 TP-V2-097 的窄切片，只处理服务器/Mac/核查面板这条可控链路。iPhone 和 Apple Watch 的设备可读性、后台刷新、WatchConnectivity、Watch cache 证据继续留给 TP-V2-085 / TP-V2-097，不在本轮执行。

## Scope

- `ai-usage-fact-check` helper：增加或修正可测试的 board update 逻辑，让定时核查能把最新摘要、基线、表格、持续缺口和建议修复写回 `docs/usage-fact-check-board.md`。
- `ai-usage-fact-check` helper：查询 Cloudflare D1 的 today total tokens，并在核查表中与主站 API today tokens 对比。
- `ai-usage-fact-check` helper：把 Mac current collection 的 today tokens 标成 `➖ 不适用` 或等价口径，说明它只证明四个额度窗口，不把它当作用户体验警告。
- `ai-usage-fact-check` helper：在 Mac popover/cache 行明确显示缓存 `generated_at`、与主站 API 的差异字段、差异值和原因。
- `docs/usage-fact-check-board.md`：保持单一落板，不新建多份核查报告。
- 测试：新增或扩展 helper 的单元测试，覆盖 D1 today tokens、Mac current 不适用口径、board update 输出和 Mac popover 差异描述。

## Out of Scope

- 不修改 iPhone App、iOS Widget、Apple Watch App、WatchConnectivity、APNs 或真机安装流程。
- 不要求 iPhone / Watch 设备可读作为本任务验收条件。
- 不切流 Cloudflare native，不变更线上 Worker 路由。
- 不修改生产 token、SSH key、Cloudflare credential、原始 usage 日志或 `config/sources.local.json`。
- 不把 `ccusage daily`、`ccusage blocks` 或本地估算伪装成官方额度状态。
- 不提交 commit。

## Red Test

- Python：构造 Cloudflare D1 查询结果包含 today usage rows，断言 helper 输出 `d1_today_total_tokens`，且核查表中 D1 行能显示 today tokens。
- Python：构造 Mac current collection 只返回四个 quota windows，断言核查表把 today tokens 标为不适用/职责外，而不是警告为数据不完整。
- Python：构造 Cloudflare 主站 API 与 Mac popover cache 不一致，断言输出包含具体差异字段、期望值、实际值和缓存 `generated_at`。
- Python：构造一份完整 fact payload，断言 board update 会更新：
  - `最后核查`
  - `当前 Cloudflare 主站 API 基线`
  - `当前状态摘要`
  - `最新核查表`
  - `持续缺口`
  - `建议修复/待办`

## Implementation

1. 先补 `tests/test_usage_fact_check_skill.py` 或等价测试，确认当前 helper 在 D1 today tokens、Mac current 口径或 board update 上失败。
2. 在 helper 内提取纯函数，负责从采集 payload 生成产品可读的核查行和 board markdown，避免测试依赖真实 Cloudflare / 设备。
3. 扩展 Cloudflare D1 查询：只查询 today total 所需的聚合结果，不读取或打印原始 usage 日志、token、密钥。
4. 调整 Mac current 行语义：四个 quota windows 准确时标为准确或不适用 today tokens，不再把职责外的 today tokens 作为体验警告。
5. 调整 Mac popover 行语义：对比主站 API 后输出具体滞后字段和缓存时间。
6. 增加 `--update-board` 或等价显式开关；定时任务使用该开关写回 `docs/usage-fact-check-board.md`，普通手动 `--pretty` 默认仍只读输出。
7. 运行最小测试和一次只读核查；如执行落板，确认 `docs/usage-fact-check-board.md` 更新到最新时间。

## Acceptance Criteria

- 定时核查结束后，`docs/usage-fact-check-board.md` 的最后核查时间、四个 quota 基线和 today tokens 与同轮主站 API 结果一致。
- D1 行能显示 today tokens；如果 D1 层无法取到，必须写出具体查询失败原因，而不是泛写“未核到”。
- Mac current collection 行不再把 today tokens 职责外标成体验警告；用户能看懂它只证明当前额度窗口。
- Mac 菜单栏缓存行能说清楚：缓存时间、哪些字段滞后、期望值、实际值、是否影响用户可见显示。
- iPhone / Watch 缺口不会阻塞本任务，也不会被写成本轮必须修复项。
- 所有输出不泄漏 token、Cloudflare key、SSH key、原始 usage 日志路径或内容。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_usage_fact_check_skill
python3 /Users/wangzhipeng/.codex/skills/ai-usage-fact-check/scripts/check_usage_facts.py --pretty --skip-iphone --skip-watch
python3 /Users/wangzhipeng/.codex/skills/ai-usage-fact-check/scripts/check_usage_facts.py --pretty --skip-iphone --skip-watch --update-board
```

如果 helper 仍未实现 `--update-board`，第二条命令应先通过，第三条应作为 Red Test 或待实现验收。

## Handoff

汇报：

- 修改了哪些 helper、测试和文档文件。
- 最新 board 的最后核查时间、Cloudflare 主站基线、D1 today tokens、Mac current 口径、Mac popover 差异结论。
- 跑过的测试命令和结果。
- 是否执行了 `--update-board`；如果没有，说明原因。
- 明确说明 iPhone / Watch 本轮未修复、未作为阻塞项。
