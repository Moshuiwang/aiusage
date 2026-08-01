# TP-V2-097 Data Freshness and Accuracy Contract

Version: V2
ID: TP-V2-097
Status: draft
Type: implementation
Depends on: TP-V2-085, TP-V2-090
Parallel with: none

## Goal

实现数据及时准确的最小合同：服务端 read model 不受旧 quota 行污染，iPhone/Watch 本地 summary cache 写入可证明，Cloudflare/native 与 origin 的 usage/source health/limits 口径可核查。

## Context

事实核查发现：

- Mac current collection 和 Mac popover cache 会产生时间差。
- iPhone 主 App 请求成功，但 App Group `last-mobile-summary.json` 未被稳定核到。
- WatchConnectivity context 可读，但不能证明 Watch 本地 cache 已写入。
- Cloudflare 当前入口仍可代理 origin，D1 不能因为存在 collection runs 就被当成生产 quota 事实源。
- 源站 `limit_windows` 裸表包含历史 cache 行，必须由 read model 过滤出用户可见有效窗口。

参考文档：

- `docs/product/data-freshness-accuracy-prd.md`
- `docs/architecture/data-freshness-accuracy.md`
- `docs/architecture/data-freshness-accuracy-database.md`
- `docs/architecture/data-freshness-accuracy-interfaces.md`

## Scope

- 服务端：调整 read model 的 effective quota window 选择规则，避免旧 `active_limits_cache` 覆盖 official/runtime rows。
- 服务端：在 `/api/mobile/summary`、`/api/summary` 或 `/api/health` 增加可选 metadata，用于区分 `backend_mode`、`canonical_store`、limits freshness。
- Cloudflare/native：确保 `/ingest-limits` shadow/dual-write 后 D1 `limit_windows` 非空，并纳入 parity 检查。
- iPhone：today summary 请求成功后，App Group `last-mobile-summary.json` 写入失败必须可诊断，不能只 `try?` 静默吞掉。
- iPhone：runtime diagnostic 增加 cache write 和 Watch push 的安全状态。
- Watch：收到 WatchConnectivity summary 后写入 Watch App Group `last-watch-summary.json`，并提供本地 receipt 或可核查诊断。
- Fact check skill：优先读取 iPhone App Group summary 和 Watch App Group summary；缺失时明确报告证据缺口。

## Out of Scope

- 不改 UI 样式、布局、文案层级。
- 不新增 Watch 直连 HTTP API。
- 不把 token 写入 App Group、shared UserDefaults 或 diagnostic。
- 不切流 Cloudflare native。
- 不 commit。

## Red Test

- Python：构造 `limit_windows` 同时包含旧 `active_limits_cache` 和新 official/runtime rows，断言 `/api/mobile/summary` 只返回新有效窗口。
- Python/Cloudflare：seed D1 后，`/api/mobile/summary` parity 覆盖 `limits.windows`，且 D1 `limit_windows` 非空。
- Swift iOS：模拟 App Group container 不可用时，today summary 请求成功但 cache write 失败，diagnostic 记录 `cacheWriteStatus=failed`。
- Swift iOS：today summary 请求成功时，`last-mobile-summary.json` 被写入并可 decode。
- Swift Watch：收到 WatchConnectivity payload 后写入 `last-watch-summary.json`，receipt/diagnostic 记录 success。
- Integration：fact-check helper 在真机可读 iPhone App Group summary；Watch 不可直连时明确区分 context evidence 和 Watch cache evidence。

## Implementation

1. 先补服务端 effective quota window tests。
2. 实现 read model 过滤和 metadata。
3. 补 D1 limits parity 检查。
4. 改 iPhone cache write 为显式结果，写入 diagnostic。
5. 改 Watch receive/write 为显式结果，写入 receipt。
6. 更新 `ai-usage-fact-check` helper 读取新增证据。
7. 跑本地单测、Swift tests、Cloudflare/native parity tests 和真机只读核查。

## Acceptance Criteria

- 同一时刻核查表能区分 current source、API read model、iPhone cache、Watch context、Watch cache。
- iPhone 真机上 App Group `last-mobile-summary.json` 可读，period 为 today。
- Watch App Group `last-watch-summary.json` 可读可 decode，period 为 today，并与 iPhone WatchConnectivity context 的 `generated_at` 对齐。若只能读取 Watch receipt，receipt 必须明确记录同一 `generated_at` 的 Watch summary 写入成功；如果设备不可用，报告为验收缺口，不用 iPhone cache 或 context 冒充 Watch 本地 cache。
- Cloudflare D1 的 `limit_windows` 与 origin read model 同口径，不能为空却被当成生产 quota。
- 旧 `active_limits_cache` 行不会进入用户可见 quota。
- 所有新增 metadata/diagnostic 不泄漏 token 或原始 provider response。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
swift test --package-path mobile/ios
/Users/wangzhipeng/.codex/skills/ai-usage-fact-check/scripts/check_usage_facts.py --pretty
```

Cloudflare/native parity 命令按 TP-V2-090 当前脚本执行。

## Handoff

汇报：

- 修改文件。
- 通过的测试和真机核查证据。
- iPhone/Watch cache 文件是否可读。
- D1/origin limits parity 结果。
- 未跑测试和原因。
