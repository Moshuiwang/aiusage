# TP-V2-099 macOS Menu Bar Quota Window Slots

Status: done

Owner: macOS Client agent

## Problem

macOS menu bar 的额度圆环使用 `outer` / `inner` 作为展示槽位，但 popover 文案固定把 `outer` 标成 `5h`、`inner` 标成 `7d`。

当 Claude 5h/session 窗口因为过期或缺少可信观测被过滤掉，而 7d/week 窗口仍然存在时，7d 会被塞进 `outer`，用户看到的是：

- `5h` 行显示 7d 的百分比。
- `7d` 行显示 `--`。

这不是后端数据缺失，也不是 7d 本身不可用，而是 macOS 菜单栏展示模型把“第一个可用窗口”误当成固定的 `5h` 槽位。

## Scope

- 只修改 macOS menu bar 展示模型。
- `5h` 槽位只展示 session / 5h 窗口。
- `7d` 槽位只展示 week / 7d 窗口。
- 如果 5h 缺少可信数据，5h 显示 `--`，不能挪用 7d。
- 如果 7d 有可信数据，7d 必须继续显示在 7d 行和内圈。

## Out of Scope

- 不改 server API。
- 不改 Cloudflare / D1 schema。
- 不改 iPhone / Apple Watch。
- 不把本地估算、过期 reset 或 cache-only 数据伪装成可信额度。

## Acceptance

- 增加失败优先测试：Claude 5h 缺失、7d 存在时，macOS menu bar state 中 `outer` 为 `--` / `0`，`inner` 为 7d 百分比。
- 现有“同一 provider/window 取最新可信观测”的行为保持不变。
- `swift test --package-path clients/macos --filter AIUsageMenuBarCoreTests.MenuBarViewModelTests` 通过。

## Verification

- 2026-06-25：先运行单测得到预期失败，确认 7d 被错误填入 5h 槽位。
- 2026-06-25：修复后运行 `swift test --package-path clients/macos --filter AIUsageMenuBarCoreTests.MenuBarViewModelTests`，6 个测试通过。
