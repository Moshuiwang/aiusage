import AIUsageWidgetCore
import SwiftUI
import WidgetKit

@main
struct AIUsageWidgetApp: App {
    private let loader = SnapshotLoader(path: SnapshotLoader.defaultPath())

    init() {
        WidgetCenter.shared.reloadAllTimelines()
    }

    var body: some Scene {
        WindowGroup {
            UsageWidgetContainer(loadState: loader.load(), path: loader.path)
                .frame(width: 420, height: 520)
        }
        .windowResizability(.contentSize)
    }
}
