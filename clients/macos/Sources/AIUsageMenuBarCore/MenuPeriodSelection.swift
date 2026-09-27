import Foundation

public struct MenuPeriodSelection: Equatable, Sendable {
    public static let periodIDs = ["today", "week", "month"]
    public let periodID: String
    public let offset: Int

    public init(periodID: String, offset: Int = 0) {
        self.periodID = Self.periodIDs.contains(periodID) ? periodID : "today"
        self.offset = self.periodID == "today" ? max(-6, min(0, offset)) : min(0, offset)
    }

    public var cacheKey: String { offset == 0 ? periodID : "\(periodID):\(offset)" }
}
