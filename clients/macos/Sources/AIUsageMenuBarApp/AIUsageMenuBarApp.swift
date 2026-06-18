import AppKit
import AIUsageMenuBarCore

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusBarController: StatusBarController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let paths = RuntimePaths()
        try? paths.ensureCreated()
        AppRuntimeLog.append("applicationDidFinishLaunching", paths: paths)
        statusBarController = StatusBarController(paths: paths)
        AppRuntimeLog.append("statusBarControllerReady", paths: paths)
    }

    func applicationWillTerminate(_ notification: Notification) {
        statusBarController = nil
    }
}
