import Foundation

/// #186：回归测试固定注入「本机 = Asia/Shanghai」，不依赖运行测试的机器自身时区——
/// 这些既有断言假设本机时区与 summary.timezone（Asia/Shanghai）当前 UTC 偏移相同（现状不变分支）。
let shanghaiTZForTests = TimeZone(identifier: "Asia/Shanghai")!
