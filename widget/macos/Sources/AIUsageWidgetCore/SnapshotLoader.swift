import Foundation

public enum SnapshotLoadState: Equatable, Sendable {
    case missing
    case unreadable(String)
    case ready(LatestSnapshot)
}

public struct SnapshotLoader: Sendable {
    public let path: String

    public init(path: String) {
        self.path = path
    }

    public func load() -> SnapshotLoadState {
        let url = URL(fileURLWithPath: path)
        guard FileManager.default.fileExists(atPath: url.path) else {
            return .missing
        }

        do {
            let data = try Data(contentsOf: url)
            let decoder = JSONDecoder()
            let snapshot = try decoder.decode(LatestSnapshot.self, from: data)
            return .ready(snapshot)
        } catch {
            return .unreadable(error.localizedDescription)
        }
    }

    public static func defaultPath() -> String {
        if let envPath = ProcessInfo.processInfo.environment["AI_USAGE_LATEST_JSON"], !envPath.isEmpty {
            return envPath
        }

        let cwd = FileManager.default.currentDirectoryPath
        let cwdCandidate = URL(fileURLWithPath: cwd).appendingPathComponent("data/latest.json").path
        if FileManager.default.fileExists(atPath: cwdCandidate) {
            return cwdCandidate
        }

        return NSString(string: "~/Documents/ai-usage-widget/data/latest.json").expandingTildeInPath
    }
}
