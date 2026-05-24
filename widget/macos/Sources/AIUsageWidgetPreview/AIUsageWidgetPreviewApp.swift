import AIUsageWidgetCore
import SwiftUI

@main
struct AIUsageWidgetPreviewApp: App {
    private let loader = SnapshotLoader(path: SnapshotLoader.defaultPath())

    var body: some Scene {
        Window("AI Usage", id: "ai-usage-widget") {
            UsageWidgetContainer(loadState: loader.load(), path: loader.path)
                .frame(width: 420, height: 520)
        }
        .windowResizability(.contentSize)
    }
}
