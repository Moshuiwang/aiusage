import Foundation

public struct RuntimePaths: Equatable, Sendable {
    public let root: URL

    public init(root: URL = RuntimePaths.defaultRoot()) {
        self.root = root
    }

    public var configURL: URL {
        root.appendingPathComponent("config.json", isDirectory: false)
    }

    public var cacheURL: URL {
        root.appendingPathComponent("last-summary.json", isDirectory: false)
    }

    public var periodCacheDirectoryURL: URL {
        root.appendingPathComponent("summaries", isDirectory: true)
    }

    public var logURL: URL {
        root.appendingPathComponent("menu-bar.log", isDirectory: false)
    }

    public func cacheURL(forPeriod periodID: String) -> URL {
        periodCacheDirectoryURL.appendingPathComponent("\(safePeriodID(periodID)).json", isDirectory: false)
    }

    public static func defaultRoot(homeDirectory: URL? = nil) -> URL {
        let home = homeDirectory ?? FileManager.default.homeDirectoryForCurrentUser
        return home
            .appendingPathComponent("Library", isDirectory: true)
            .appendingPathComponent("Application Support", isDirectory: true)
            .appendingPathComponent("ai-usage-widget", isDirectory: true)
            .appendingPathComponent("macos-menu-bar", isDirectory: true)
    }

    public func ensureCreated() throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: periodCacheDirectoryURL, withIntermediateDirectories: true)
    }

    private func safePeriodID(_ periodID: String) -> String {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        let scalars = periodID.unicodeScalars.map { scalar -> Character in
            allowed.contains(scalar) ? Character(scalar) : "-"
        }
        let value = String(scalars)
        return value.isEmpty ? "today" : value
    }
}
