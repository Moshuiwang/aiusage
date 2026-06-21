#if os(watchOS)
import Foundation
import SwiftUI
import WatchConnectivity
import WidgetKit

@main
struct AIUsageWatchApp: App {
    @StateObject private var model = WatchSummaryModel()

    var body: some Scene {
        WindowGroup {
            AIUsageWatchSummaryView(summary: model.summary)
        }
    }
}

final class WatchSummaryModel: NSObject, ObservableObject, WCSessionDelegate, @unchecked Sendable {
    @Published var summary: WatchMobileSummary?

    override init() {
        self.summary = WatchSummaryStore.read()
        super.init()
        activateSession()
    }

    private func activateSession() {
        guard WCSession.isSupported() else {
            return
        }
        let session = WCSession.default
        session.delegate = self
        session.activate()
        apply(applicationContext: session.receivedApplicationContext)
    }

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        apply(applicationContext: session.receivedApplicationContext)
    }

    func session(
        _ session: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        apply(applicationContext: applicationContext)
    }

    func session(
        _ session: WCSession,
        didReceiveUserInfo userInfo: [String: Any] = [:]
    ) {
        apply(applicationContext: userInfo)
    }

    private func apply(applicationContext: [String: Any]) {
        guard let data = applicationContext["mobileSummary"] as? Data,
              let decoded = try? JSONDecoder().decode(WatchMobileSummary.self, from: data)
        else {
            return
        }
        guard decoded.period.id == "today" else {
            return
        }
        WatchSummaryStore.write(decoded)
        WidgetCenter.shared.reloadTimelines(ofKind: "AIUsageWatchWidget")
        DispatchQueue.main.async {
            self.summary = decoded
        }
    }
}
#endif
