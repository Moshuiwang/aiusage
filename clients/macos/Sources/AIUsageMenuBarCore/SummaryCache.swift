import Foundation

public enum SummaryCache {
    public static func load(from url: URL) -> MobileSummary? {
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }
        return try? JSONDecoder().decode(MobileSummary.self, from: data)
    }

    public static func save(_ summary: MobileSummary, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder().encode(summary)
        try data.write(to: url, options: Data.WritingOptions.atomic)
    }
}
