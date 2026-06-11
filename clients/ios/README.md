# iOS Client

目标用户体验：

- iPhone App 是移动端主体验。
- iOS Widget 只做 glanceable 摘要。
- App / Widget 只消费 `/api/mobile/summary` 或 App 准备好的摘要，不执行采集。

当前实现仍保留在：

- `mobile/ios`
- `mobile/ios-xcode`

迁移到 `clients/ios` 前必须单独开任务包，先保证 Swift Package 测试和 Xcode build 路径可验证。
