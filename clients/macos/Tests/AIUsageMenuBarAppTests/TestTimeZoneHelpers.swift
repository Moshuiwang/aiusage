import Foundation

/// #186：回归测试固定注入「本机 = Asia/Shanghai」，不依赖运行测试的机器自身时区——
/// 这些既有断言假设本机时区与 summary.timezone（Asia/Shanghai）当前 UTC 偏移相同（现状不变分支）。
let shanghaiTZForTests = TimeZone(identifier: "Asia/Shanghai")!

/// #186 P1 修复：MainActor 隔离的可变时区盒子，供测试模拟「用户在系统设置里切换了时区」——
/// deviceTimeZoneProvider 闭包读它的 timeZone，测试改这个属性再发 NSSystemTimeZoneDidChange
/// 通知，验证生产代码是否真的每次重建都重新读 provider，而不是缓存 init 时的第一次读数。
@MainActor
final class TimeZoneBox {
    var timeZone: TimeZone
    init(_ timeZone: TimeZone) { self.timeZone = timeZone }
}
