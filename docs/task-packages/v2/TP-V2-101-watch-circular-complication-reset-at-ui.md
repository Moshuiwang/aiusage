# TP-V2-101 Watch Circular Complication Reset At UI

Version: V2
ID: TP-V2-101
Status: done
Type: implementation
Depends on: TP-V2-084
Parallel with: none

## Goal

把 Apple Watch 圆形小组件改成已确认的 Reset At 双圆环设计，让用户抬腕能一眼看到 5 小时额度重置时间和两个额度窗口的使用状态。

## Context

当前设计规格已经在 `docs/product/watch-circular-complication-reset-at-ui.md` 收敛：

- 圆形小组件中心显示 5 小时窗口 `reset_at` 转换后的本地时间，例如 `14:48`。
- 外圈展示 5 小时窗口使用百分比。
- 内圈展示长窗口使用百分比。
- Codex 使用蓝色系，Cloud / Claude 使用暖橙色系。
- 缺少可信 `reset_at` 时显示 `--:--`。

这件事是纯 Watch 圆形小组件 UI 改版，不是刷新链路任务。TP-V2-085 负责 iPhone 到 Watch 的刷新同步，TP-V2-100 负责同步失败诊断；本任务只负责圆形 complication 的用户可见设计落地。

## Scope

- 修改 Watch `.accessoryCircular` 展示，让 Codex 和 Cloud / Claude 都使用同一套 Reset At 双圆环布局。
- 中心主信息显示本地 `HH:MM` 格式 Reset At 时间。
- 中心次信息显示安全账号短名；如果 41mm 尺寸拥挤，优先保留 `HH:MM`，可以隐藏账号短名。
- 外圈固定代表 5 小时窗口，内圈固定代表长窗口，不能因为 5 小时缺失就用长窗口顶替外圈。
- 缺少可信 5 小时窗口、`reset_at` 缺失或解析失败时，中心时间显示 `--:--`。
- 数据 stale 时必须保留可见 stale 信号，不能让旧缓存看起来像实时额度。
- 5 小时窗口缺失、不可信、非 official/observed/ok 时，外圈按降级态显示，不得用长窗口顶替外圈，也不得画成可信满信息。
- 调整圆环间距、线宽和中心字号，确保 41mm / 45mm / 49mm 圆形小组件都不挤压。
- 增加静态或 Swift 测试，锁住 Reset At 文案规则、窗口槽位和无敏感信息边界。

## Out of Scope

- 不改 iPhone -> Watch 刷新链路。
- 不改 WatchConnectivity、App Group cache、WidgetKit timeline reload 或后台刷新策略。
- 不改 TP-V2-100 的诊断字段。
- 不改服务端、Cloudflare Worker、D1、SQLite schema 或 `/api/mobile/summary` 合同。
- 不让 Watch 直连服务器，不在 Watch 保存 token、server URL 或 provider 原始响应。
- 不开发第三方完整自定义表盘，只改系统表盘上的 WidgetKit circular accessory。
- 不改 `.accessoryRectangular` 或 `.accessoryInline`，除非编译共享组件必须做无视觉影响的适配。

## Red Test

- Swift 或静态测试：圆形 complication 使用 `reset_at` 渲染本地 `HH:MM`，不是倒计时、日期或 provider 名。
- Swift 或静态测试：`reset_at` 缺失、解析失败或 5 小时窗口不可信时显示 `--:--`。
- Swift 或静态测试：5 小时窗口只进入外圈，长窗口只进入内圈；5 小时缺失时不能把长窗口挪到外圈。
- Swift 或静态测试：stale summary 在圆形 complication 内有可见 stale 信号，旧数据不能只显示正常 `HH:MM` 和实体圆环。
- Swift 或静态测试：Codex 与 Cloud / Claude 使用同一布局但不同颜色语义。
- Swift 或静态测试：圆形 complication 内部不显示 token、server URL、原始 provider 响应、`Codex`、`Cloud`、`5H Reset`、日期或倒计时。
- 可选 snapshot / preview 检查：41mm 安全尺寸下中心 `HH:MM` 不压住内圈。

## Implementation

1. 先补失败测试或静态断言，覆盖 Reset At、缺失态、双圆环槽位和敏感信息边界。
2. 找到 Watch WidgetKit `.accessoryCircular` 的渲染入口，保持 Watch App 和其他 accessory family 行为不被顺手重写。
3. 把圆形 complication 的中心内容改为账号短名 + Reset At 本地 `HH:MM`。
4. 固定外圈 / 内圈窗口含义，缺失时展示降级状态，不挪用其他窗口。
5. 按 `docs/product/watch-circular-complication-reset-at-ui.md` 调整圆环半径、线宽、间距、中心字号和颜色。
6. 使用 preview、simulator 或可用真机截图检查 41mm / 45mm / 49mm 可读性。
7. 跑最小 Watch / iOS Xcode 集成测试和 diff check。

## Acceptance Criteria

- Watch 圆形小组件中心主视觉是 Reset At 本地时间，不是倒计时或日期。
- Codex 和 Cloud / Claude 的圆形小组件都使用同一套双圆环信息层级。
- 外圈始终代表 5 小时窗口；内圈始终代表长窗口。
- `reset_at` 缺失或不可用时显示 `--:--`，不是空白或错误文本。
- stale summary 有明确 stale 信号；旧缓存不能伪装成实时状态。
- 5 小时窗口缺失或不可信时外圈为空/降级态，不能挪用长窗口。
- 41mm 尺寸下 `HH:MM` 清晰可读，且不贴住或压住内圈圆环。
- 小组件内部不显示 provider 全名、日期、`5H Reset`、token、server URL 或原始响应。
- 不改变刷新同步链路、诊断链路或服务端数据口径。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' build CODE_SIGNING_ALLOWED=NO
git diff --check
```

Manual visual verification when device state allows:

```text
1. Build and install the iPhone app with the embedded Watch app/widget.
2. Add AI Usage Codex and AI Usage Claude circular complications to a supported system watch face.
3. Confirm both show Reset At as local HH:MM and keep 5h / long-window rings in the correct slots.
4. Confirm missing reset_at renders --:--.
5. Confirm 41mm-safe layout remains readable or hides account short name while preserving HH:MM.
```

## Handoff

- Report changed Watch widget files and tests.
- Report automated test and build results.
- Attach simulator or physical Watch screenshots for Codex normal, Cloud / Claude normal, and missing `reset_at` states when available.
- State whether 41mm, 45mm, and 49mm layouts were visually checked.
- State explicitly that refresh sync, diagnostics, server API, and data storage were not changed.
