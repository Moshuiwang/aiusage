# PRD: Apple Watch Companion and TestFlight Stable Install

## 背景

当前 Apple Watch 上的 `AI Usage` 体验更像开发安装：项目里已有 `AIUsageWatchApp`，但它没有形成稳定的 iPhone companion 安装体验，也没有可添加到系统表盘的 WidgetKit accessory。用户已经在手表上看不到 App，表盘入口也随之消失。

本轮目标不是上架给公众，也不是扩大到团队使用；目标是让单个用户自己的 iPhone 和 Apple Watch 能稳定安装、稳定显示、稳定更新。

## 产品目标

用户从 TestFlight 安装 `AI Usage` 后，应获得这条体验：

1. iPhone 上安装 `AI Usage`。
2. Apple Watch 可以作为 iPhone App 的配套能力被安装和管理。
3. 手表 App 可以查看最新摘要和缓存状态。
4. 系统表盘可以选择 `AI Usage` 的 WidgetKit accessory。
5. 90 天 TestFlight build 有效期内，不再依赖 Xcode 临时安装。

## 用户体验范围

### iPhone App

- 仍然是完整移动端查看入口。
- 负责拉取 `/api/mobile/summary`。
- 负责保存最近一次可用摘要。
- 已通过 TP-V2-070 建立 MobileSummary 到 Apple Watch 的同步基础，本轮必须复用并验收这条链路。
- 负责触发 iOS Widget 和 Watch 相关展示刷新。

### Apple Watch App

- 是 iPhone App 的 companion 体验，不是独立数据产品。
- 显示用户抬腕时最关心的信息：
  - Codex 两类额度使用百分比。
  - 对应 reset time。
  - 今日总用量。
  - 最近更新时间 / stale 状态。
- 无网络或同步失败时，继续显示最近一次成功摘要，并明确标记过期。
- 不做复杂 drilldown，不做趋势图，不做来源长列表。

### 表盘 WidgetKit accessory

- 目标是“抬腕一秒判断状态”，不是完整 dashboard。
- 表盘组件必须由 watchOS WidgetKit extension 提供，并嵌入 Watch App；不能只改现有 iOS Widget extension。
- Watch App 和 watchOS WidgetKit extension 必须通过同一个 watchOS App Group 共享缓存，不能让表盘组件读取 Watch App 私有缓存目录。
- 主信息优先级：
  1. Codex 额度百分比。
  2. reset time。
  3. 今日总用量或数据新鲜度。
- 首批支持普通 Apple Watch 可用的 WidgetKit accessory family：
  - `.accessoryRectangular`：推荐主承载，展示额度和 reset time。
  - `.accessoryCircular`：紧凑承载，展示额度状态。
  - `.accessoryInline`：文字承载，展示额度或 stale 状态。
- `.accessoryCorner` 作为后续可选项，不阻塞首批验收。

### TestFlight

- 用公司稳定 Apple Developer 组织账号上传 build。
- 用户通过 TestFlight 安装 iPhone App，并让 Watch companion 跟随安装。
- 每个 build 最长可用 90 天；在第 70-80 天发新 build，避免突然过期。
- 本阶段不要求公开 App Store 发布。

## 非目标

- 不开发第三方完整自定义表盘；Apple Watch 只支持系统表盘上的 WidgetKit accessory。
- 不让 Watch 端直接调用 `ccusage`。
- 不让 Watch 端 SSH、读取 SQLite、读取 `.claude` / `.codex` 原始日志。
- 不在 Watch 端调用官方 limits provider。
- 不新增团队账号、多租户、云同步。
- 不把 TestFlight 当成永久正式分发；它是 90 天滚动 beta 分发。

## 数据和接口判断

本轮不需要新增数据库表，也不需要新增服务端接口。

Watch App 和 WidgetKit accessory 使用 iPhone App 已经拿到的 mobile summary 派生数据：

```text
/api/mobile/summary
-> iPhone App cache
-> WatchConnectivity / shared summary
-> Watch App
-> watchOS App Group cache
-> Watch WidgetKit accessory
```

如果后续发现 Watch 需要更小的 DTO，优先在 iPhone 端裁剪，不新增 server endpoint。只有当 `/api/mobile/summary` 缺少可靠字段，才另开服务端接口或 DTO 任务包。

当前实现已经有 iPhone -> Watch 的 MobileSummary 同步基础。本轮默认沿用现有合同；只有在表盘组件确实需要更小展示模型时，才允许在 iPhone 端派生 DTO，并必须避免和现有 MobileSummary 同步并行成两套长期合同。

本轮还必须把 Watch 端缓存从“只有 Watch App 自己能读”升级为“Watch App 和表盘 WidgetKit accessory 都能读”的共享缓存。这个共享只发生在 Watch 设备本地，不新增服务端接口，也不把 token 下发到 Watch。

## 成功标准

- 用户从 TestFlight 安装一次后，iPhone App、Watch App、表盘组件都能被系统正常管理。
- Watch 端不再依赖 Xcode 临时安装才能出现。
- 表盘组件可以在支持的系统表盘上作为 `AI Usage` 的 WidgetKit accessory 被添加，并显示 Codex 额度与 reset time。
- 表盘组件读取的是 Watch App 同步后的共享缓存，不显示 fixture 或空数据作为成功状态。
- Watch 端离线或摘要过期时，用户能看出“这是旧数据”。
- iPhone App、iOS Widget、Watch App、表盘组件看到的 usage / limits 口径一致。
- 90 天过期前可以通过新 TestFlight build 平滑更新。

## 风险

| 风险 | 用户影响 | 处理方式 |
| --- | --- | --- |
| Watch target 没有真正嵌入 iPhone App | 手表 App 仍像临时安装，可能消失 | 调整为 companion 安装结构，并用真机验证。 |
| 只有 Watch App，没有 watchOS WidgetKit extension | 用户仍不能在表盘稳定查看 | 新增嵌入 Watch App 的 watchOS widget extension，并声明 accessory family。 |
| watchOS widget extension 读不到 Watch App 私有缓存 | 表盘组件出现但没有真实额度 | 为 Watch App 和 watchOS widget extension 配置同一个 App Group，并迁移缓存读取。 |
| TestFlight build 到期 | 90 天后无法继续测试 | 建立 70-80 天发新版节奏。 |
| Watch 显示旧缓存但不提示 | 用户误以为实时数据 | 所有 Watch 面必须显示更新时间或 stale 状态。 |
| Watch 直接拉服务端失败 | 小屏体验不稳定，耗电和网络复杂度上升 | Watch 优先消费 iPhone 同步摘要。 |

## 后续任务建议

1. 调整 Xcode 工程，让 Watch App 成为 iPhone App 的稳定 companion 安装能力。
2. 新增嵌入 Watch App 的 watchOS WidgetKit extension，首批支持 `.accessoryRectangular`、`.accessoryCircular`、`.accessoryInline`。
3. 补 companion embed、watchOS widget extension、accessory family、Watch App Group cache、cache/stale 测试和真机验收。
4. 归档 TestFlight 内测发布步骤，包括 build 号、有效期和更新节奏。
