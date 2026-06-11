# Widget Configuration Sharing Design

## 结论

本轮只做设计，不实现共享配置。

当前 iOS App 已经可以让用户在 App 内填写 server URL 和 token；但 iOS Widget 仍只展示随包带的 `mobile-summary.json` fixture。用户现在的真实风险是：App 设置成功后，Widget 不会自动读取同一份配置，也不会请求 live `/api/mobile/summary`。如果直接把 token 放进 shared UserDefaults，用户的访问凭据会从 Keychain 边界滑到普通偏好存储里，风险不可接受。

下一轮实现前必须先建立 App Group 和 Keychain access group。没有这两个 entitlement，不允许让 Widget 读取 live server/token。

## 当前真实状态

| 职责 | 当前 owner | 当前行为 |
| --- | --- | --- |
| App server URL | `MobileSummaryRuntimeConfig` | 读取 env / App `UserDefaults` / bundle fallback，保存到 App 自己的 `AIUsageAPIBaseURL`。 |
| App token | `KeychainTokenStore` via `MobileTokenStore` | 保存到 App 私有 Keychain item，不再从 `AIUsageAPIToken` UserDefaults 读取。 |
| Install-time token | `install_device_with_live_config.py` / App `Info.plist` | 安装脚本仍校验并注入 bundle token，但 App 运行时不再读取该 token；这会影响首次安装后是否能自动连上服务。 |
| App live summary | `LiveSummaryContainerView` | 用 server URL + Keychain token 调 `/api/mobile/summary`。 |
| Widget summary | `AIUsageMobileWidget.swift` | 只从 extension bundle 读取 `mobile-summary.json` fixture。 |
| Widget token | none | 当前不读 token，也不请求 live API。 |
| App Group | none | Xcode project / `project.yml` 尚未配置 application group entitlement。 |
| Keychain access group | none | Xcode project / `project.yml` 尚未配置 shared keychain entitlement。 |

## 目标用户体验

- 用户在 App 设置 server URL 和 token 后，Widget 可以使用同一套配置刷新 live summary。
- 如果配置缺失，Widget 显示“需要打开 App 完成设置”的降级状态，而不是展示误导性的旧 fixture。
- 如果 token 不可读或服务不可达，Widget 显示安全的失败状态，不泄漏 token、URL path 或底层错误。
- App 设置保存成功后触发 WidgetKit reload timeline，让 Widget 尽快更新。

## 依赖方向

```text
iOS App settings
-> App Group shared UserDefaults: non-secret config only
-> Keychain access group: token only
-> WidgetKit provider
-> MobileSummaryAPIClient
-> /api/mobile/summary
```

允许共享：

- `AIUsageAPIBaseURL`：可放入 App Group shared UserDefaults。
- `AIUsagePeriod`：可放入 App Group shared UserDefaults。
- 上次成功摘要的最小缓存：可放入 App Group container，必须是 `/api/mobile/summary` DTO，不包含 token。

必须留在 Keychain：

- API token。
- 任何未来 bearer credential。

## 必须建立的安全边界

- App 和 Widget target 必须拥有同一个 App Group entitlement，例如 `group.com.wangzhipeng.aiusage.mobile`。
- App 和 Widget target 必须拥有同一个 Keychain access group；`KeychainTokenStore` 需要支持 access group 参数。
- shared UserDefaults 只能保存 non-secret 配置，不能保存 token。
- Widget 读取配置必须走只读 adapter / read-only adapter，不能在 Widget 内写 token。
- Widget 网络请求必须复用 `MobileSummaryRuntimeConfig.isTrustedServer` 的 trust policy，不能单独放宽 HTTP / localhost / 裸 IP。
- Widget 错误文案不得显示 token、Authorization header、Keychain raw status 或完整异常堆栈。

## 新功能应该放哪里

| 新能力 | 应放位置 |
| --- | --- |
| App Group suite name 常量 | `AIUsageMobileCore` 中新增 runtime config 常量或 adapter。 |
| shared UserDefaults adapter | `AIUsageMobileCore`，只处理 server URL / period / cached summary。 |
| shared Keychain token store | iOS App / Widget 可复用的 Keychain store，仍实现 `MobileTokenStore`。 |
| Widget live provider | `AIUsageMobileWidget.swift` 的 TimelineProvider。 |
| Widget 降级摘要状态 | `WidgetSummaryBuilder` 或 Widget provider 的明确状态模型。 |
| entitlement / Xcode 配置 | `mobile/ios-xcode/project.yml` 和生成后的 Xcode project。 |
| 架构保护测试 | `tests/test_ios_xcode_integration.py` 和 Swift runtime tests。 |

## 禁止事项

- 禁止把 token 写入 shared UserDefaults。
- 禁止把 token 写入 App Group 文件。
- 禁止 Widget 使用 bundle `AIUsageAPIToken`。
- 禁止 Widget 自己定义一套 server trust policy。
- 禁止为了让 Widget 先跑起来而接受任意 HTTP、localhost、内网 IP 或裸 IP。
- 禁止改变 `/api/mobile/summary` 合约。
- 禁止改 SQLite schema。
- 禁止把 fixture 当成 live 数据继续展示给已配置用户。

## 测试规则

实现轮必须先补失败测试：

- Swift：App 保存配置后，shared UserDefaults 里只有 server URL / period，没有 token。
- Swift：Widget runtime loader 能从 App Group suite 读取 server URL，并从 shared Keychain token store 读取 token。
- Swift：Widget runtime loader 拒绝 HTTP / localhost / 裸 IP，和 App trust policy 一致。
- Python/Xcode integration：App target 和 Widget target 都声明 App Group 和 Keychain access group entitlement。
- Python/Xcode integration：Widget extension 不包含 `AIUsageAPIToken` bundle fallback。
- Widget provider：配置缺失时显示 setup required，不继续把 fixture 伪装成 live summary。

## 立即收敛的问题

P1：

- 设计已明确，但工程尚未配置 App Group / Keychain access group。没有它们，Widget 不能安全读取用户配置。

P2：

- Widget 当前 fixture 展示容易让用户误以为已经接入 live 数据。实现轮需要加“配置缺失 / live 不可用”状态。

P3：

- App 保存设置后尚未触发 WidgetKit reload timeline；实现轮应在保存成功后刷新 Widget。
- 安装脚本仍保留 Info.plist token 注入/校验；后续应单独收敛为 Keychain 首次写入或明确的首次设置流程。
