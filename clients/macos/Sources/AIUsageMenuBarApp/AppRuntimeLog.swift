import AIUsageMenuBarCore
import Foundation

enum AppRuntimeLog {
    static func append(_ message: String, paths: RuntimePaths) {
        let timestamp = ISO8601DateFormatter().string(from: Date())
        let line = "[\(timestamp)] \(message)\n"
        do {
            try paths.ensureCreated()
            if FileManager.default.fileExists(atPath: paths.logURL.path) {
                let handle = try FileHandle(forWritingTo: paths.logURL)
                try handle.seekToEnd()
                try handle.write(contentsOf: Data(line.utf8))
                try handle.close()
            } else {
                try line.write(to: paths.logURL, atomically: true, encoding: .utf8)
            }
        } catch {
            // Runtime logging is best-effort; it must never prevent the menu bar item from appearing.
        }
    }
}
