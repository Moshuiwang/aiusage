# Mobile App Design Brief

## 目标

下一阶段产品客户端方向是 iPhone App + iOS Widget。

iPhone App 负责完整查看和 drilldown；iOS Widget 负责 glanceable 摘要。macOS Widget 不再作为后续产品交付目标。

## 设计原则

1. 先设计信息架构，再写 SwiftUI。
2. 先用手机尺寸可交互原型验证布局和交互，再拆 iOS 实现任务包。
3. 所有展示块必须能追溯到 canonical store、Web API 或派生快照字段。
4. 没有可信 limits 时，界面降级为 daily usage 和 source health，不展示伪官方 quota。
5. iOS Widget 只做摘要，不做完整 dashboard。
6. macOS 端只保留 collector / pusher / server 运维价值，不再投入原生 Widget UI。

## 目标用户

当前只服务单个个人用户：

- 同时使用 Mac、Linux server、Windows desktop 或其他终端。
- 关心今天和当前窗口的 AI coding usage。
- 需要知道数据是否新鲜、哪个 source 失败、额度窗口是否可信。

## iPhone App 信息架构草案

### Home

首屏回答四个问题：

- 今天用了多少。
- 当前可信 limits 窗口还剩多少或何时 reset。
- 哪些设备 / agent 是主要用量来源。
- 数据是否新鲜，有没有 source 失败。

首屏候选模块：

- Today usage summary。
- Current limit window summary。
- Source health strip。
- Top sources / agents。
- Last updated。

### Sources

展示每个 source 的状态：

- source id / machine / OS user。
- agent coverage。
- last observed / last pushed。
- status。
- 最近非敏感错误摘要。

### Breakdown

支持 drilldown：

- by machine。
- by OS user。
- by agent。
- by model。
- by date。

### Limits

只展示可信来源：

- Claude Code 5h / weekly window。
- Codex window。
- reset time。
- observed_at。
- confidence / source_type。

缺失或 unsupported 时要明确显示原因，不用历史 token 估算成官方状态。

### Settings

早期只保留必要配置查看和诊断入口：

- server URL / current account label。
- source list。
- push / sync health。
- app cache status。

不要在早期做复杂账户体系、团队管理或公共云同步。

## iOS Widget 信息密度

### Small

- 主指标：today total 或 current window remaining。
- 辅助：last updated。
- 状态：ok / stale / partial failure。

### Medium

- today total。
- current limit window。
- top source / agent。
- health summary。

### Large

后续再考虑，不作为第一版必要范围。

## 原型协作方式

第一轮先做手机尺寸 Web prototype：

1. 固定 Home / Sources / Breakdown / Limits 四个视图。
2. 使用 fixture 或 mock snapshot，不接真实生产数据。
3. 用浏览器验证 mobile viewport。
4. 用户在 Codex in-app browser 里对具体区域做标注。
5. 标注收敛后再写 iOS SwiftUI / WidgetKit 任务包。

## 非目标

- 不继续设计 macOS Widget。
- 不做团队 SaaS。
- 不做公共云同步。
- 不直接读取 SQLite 到移动端。
- 不让移动端执行 `ccusage`、SSH 或 official provider 采集。
- 不把 estimated usage 显示成 observed quota。

## 下一步任务包候选

- `TP-V2-039-mobile-app-design-prototype`：建立手机尺寸 Web prototype、fixture 数据和浏览器验证。
- `TP-V2-040-ios-api-contract`：固定 iPhone App / iOS Widget 所需只读 API 或 snapshot contract。
- `TP-V2-041-ios-swiftui-shell`：在设计确认后创建 SwiftUI shell 和状态测试。
