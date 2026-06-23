# Data Freshness and Accuracy PRD

Date: 2026-06-23
Status: draft for implementation planning

## 一句话目标

让 AI Usage 的每个入口都能显示同一套及时、准确、可核查的数据；当数据来自缓存或同步链路时，系统必须能证明它是什么时间生成、什么时候写入、是否已经送到对应设备。

本 PRD 不处理 UI 改版。它只定义数据正确性、缓存落盘、服务端事实源和核查能力。

## 背景

本次事实核查发现，用户看到的数字不一定来自同一个“当下事实源”：

- Mac 当前采集值和 Mac popover 本地缓存可能不同步。
- iPhone 主 App 可以成功请求生产 API，但 App Group 的 `last-mobile-summary.json` 没有被核到，导致 iOS Widget / Watch fallback 缺少可证明的本地摘要。
- Watch 可以核到 iPhone 发出的 WatchConnectivity context，但不能证明 Watch 本地 cache 已写入或屏幕已刷新。
- `aiusage.chunbai.com` 当前经 Cloudflare Worker 入口访问，但生产读数仍来自阿里源站；Cloudflare D1 侧还没有成为生产事实源。
- 源站 `limit_windows` 裸表含历史缓存行，直接读表会把旧值误认为 UI 当前值；用户可见事实应以 read model/API 为准。

这些问题的共同点是：数据链路缺少“可证明的新鲜度”和“缓存落盘证据”。

## 用户问题

| 场景 | 当前风险 | 目标体验 |
| --- | --- | --- |
| 用户看 Mac popover | 可能看到上一次缓存，而不是当前采集结果 | 系统能解释 popover 数据来自哪次 summary，是否落后于当前采集 |
| 用户看 iPhone | 主 App 请求成功，但本地 summary cache 是否写成功不清楚 | 请求成功后，本地 App Group cache 写入结果可被诊断和核查 |
| 用户看 iOS Widget | Widget 依赖 App Group summary，若 cache 缺失会退回空/旧数据 | Widget 的数据来源必须是最近成功摘要或明确的无数据状态 |
| 用户看 Apple Watch | 只能证明 iPhone 发过 context，不能证明 Watch 写入本地 cache | Watch 收到 summary 后应写本地 cache，并能被核查工具证明 |
| 用户查网页/手机/API | Cloudflare 入口和阿里源站/D1 的事实边界不清晰 | 每个 API 响应能说明 backend mode 和数据更新时间 |
| 用户让 Codex 核查 | 需要逐端手工找证据，容易混淆裸 DB 与 read model | 核查工具能按固定证据链输出同口径表格 |

## 产品原则

1. **一个用户可见事实源**：客户端展示用 `/api/mobile/summary` 或 `/api/summary` 派生结果，不直接相信裸 SQLite/D1 表。
2. **缓存是事实的一层，不是黑盒**：每个客户端本地缓存都必须有可核查的写入结果、生成时间和数据来源。
3. **旧数据可以保留，但不能伪装成实时**：失败时保留 last good summary，但必须能判断 stale。
4. **Cloudflare 与源站要分清**：Cloudflare proxy、Native Worker、D1 staging/prod 的角色必须在健康和核查输出里可见。
5. **先保证数据正确，再考虑 UI 呈现**：本轮不改视觉，不重新设计卡片、布局、文案层级。

## 目标范围

### P0: 核心准确性

- `/api/mobile/summary` 继续作为移动端、macOS 菜单栏、Watch 同步的统一只读 DTO。
- read model 必须只选择当前有效的 official/observed/ok quota windows，避免裸表旧行污染用户可见值。
- iPhone 主 App 请求成功后，必须写入 App Group `last-mobile-summary.json`；写入失败不能被静默吞掉。
- iPhone runtime diagnostic 必须记录：
  - API 请求是否成功；
  - summary `generated_at`；
  - App Group cache 是否写成功；
  - WatchConnectivity push 是否尝试、是否成功排队；
  - 失败原因的安全摘要。
- Watch 收到 summary 后，必须写入 Watch App Group `last-watch-summary.json`；写入失败可诊断。
- 核查 skill 必须区分三层证据：iPhone App Group summary、WatchConnectivity context、Watch App Group summary。验收 Watch 落盘时，不能用 iPhone cache 或 context 替代 Watch App Group summary；如果只能读到 receipt，receipt 必须明确证明同一 `generated_at` 的 Watch summary 已成功写入。

### P1: 服务端事实源收口

- Cloudflare `/api/health` 或等价诊断结果能说明当前入口是 proxy 还是 native。
- D1 进入生产前，`usage`、`source health`、`limit_windows` 必须与阿里源站 API 逐项 parity。
- D1 `limit_windows` 不能为空还被当作生产额度事实源。
- `/ingest-limits` 在 proxy/native/dual-write 阶段的写入结果必须可核查。

### P2: 长期运维核查

- `ai-usage-fact-check` skill 输出表格时，把“实时源值”和“已写入各端缓存的值”分开。
- 每次核查能给出“不一致原因”：缓存未刷新、App Group 未写入、Watch 未收到、D1 未同步、源站旧行污染等。

## 非目标

- 不改 UI 样式、布局、图表、按钮和组件层级。
- 不新增 Watch 直连服务器能力；Watch 仍由 iPhone 同步 today summary。
- 不把 token 放入 App Group 文件或 shared UserDefaults。
- 不让客户端直接读取 SQLite/D1。
- 不从 Mac 直接同步或解析远程 `~/.claude`、`~/.codex` 原始日志目录。
- 不把 `ccusage daily`、`ccusage blocks` 或估算结果伪装成官方额度。

## 验收标准

| 验收项 | 通过标准 |
| --- | --- |
| Mac | 当前采集、popover cache、生产 API 三者可分别核查，并能解释差异 |
| iPhone | 真机启动后存在成功诊断，且 App Group `last-mobile-summary.json` 可读、period 为 today |
| iOS Widget | 读取 App Group summary；无 cache 时不把 bundle fixture 当 live 数据 |
| Watch | iPhone WatchConnectivity context 可读，Watch App Group `last-watch-summary.json` 可读，二者 summary id/timestamp 一致 |
| 源站 | `/api/mobile/summary?period=today` 的 limits 与 read model 规则一致，不受旧 `active_limits_cache` 行污染 |
| Cloudflare | route、backend mode、D1 行数、D1 latest collection/limits 状态可核查 |
| Fact check | 一条命令输出来源、四个 quota 数字、更新时间、核查方式、已知问题 |

## 成功判定

当用户再次问“现在 Mac、iPhone、Watch、网页分别是多少”时，系统不仅能给数字，还能回答：

- 这个数字来自哪一层；
- 是什么时候生成的；
- 是否已经写入该端本地缓存；
- 如果不同端不一致，差异是由缓存延迟、未落盘、同步延迟还是后端事实源差异造成。
