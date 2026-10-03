import AppKit
import AIUsageMenuBarCore

/// Owns the independent bundled worker; display models continue to read summary only.
@MainActor
final class CollectorController {
    let store: CollectorSettingsStore
    private var process: Process?
    private var restartRequested = false
    private var failure = false
    private(set) var wantsLoginItem = false

    init(root: URL) { store = CollectorSettingsStore(root: root) }
    var isRunning: Bool { process?.isRunning == true }
    var statusText: String { failure ? "本机采集无法启动，请重新安装 App" : store.statusText(isRunning: isRunning) }

    func start() {
        guard store.isEnabled, process == nil else { return }
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/AIUsageCollector.app/Contents/MacOS/AIUsageCollector")
        let child = Process()
        child.executableURL = helper
        child.arguments = ["--root", store.root.path, "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        var environment = ProcessInfo.processInfo.environment
        if let sha = Bundle.main.object(forInfoDictionaryKey: "AIUsageBuildSHA") as? String { environment["AI_USAGE_BUILD_SHA"] = sha }
        if let data = try? Data(contentsOf: store.root.appendingPathComponent("last-upgrade.json")),
           let history = try? JSONSerialization.jsonObject(with: data) as? [String: String] {
            for (key, variable) in [("status", "AI_USAGE_LAST_UPGRADE_STATUS"), ("from_version", "AI_USAGE_LAST_UPGRADE_FROM_VERSION"),
                                    ("to_version", "AI_USAGE_LAST_UPGRADE_TO_VERSION"), ("finished_at", "AI_USAGE_LAST_UPGRADE_FINISHED_AT")] {
                if let value = history[key] { environment[variable] = value }
            }
        }
        child.environment = environment
        child.standardOutput = FileHandle.nullDevice
        child.standardError = FileHandle.nullDevice
        child.terminationHandler = { [weak self] child in
            let code = child.terminationStatus
            Task { @MainActor in
                guard let self else { return }
                self.process = nil
                if self.restartRequested {
                    self.restartRequested = false
                    self.start()
                } else if code != 0 {
                    self.failure = true
                }
            }
        }
        do {
            try child.run()
            process = child
            failure = false
        } catch { failure = true }
    }

    func stop() {
        restartRequested = false
        if process?.isRunning == true { process?.terminate() }
    }

    func collectNow() {
        guard store.isEnabled else { return }
        // Restart gracefully after the previous worker and its child have stopped.
        if let process, process.isRunning {
            restartRequested = true
            process.terminate()
        } else { start() }
    }

    func toggle() {
        do {
            try store.setEnabled(!store.isEnabled)
            if store.isEnabled { start() } else { stop() }
        } catch { showError("无法保存本机采集设置") }
    }

    func configure() -> Bool {
        let alert = NSAlert()
        alert.messageText = "连接 AI Usage"
        alert.informativeText = "新机器留空令牌即可申请授权，由管理员核对配对码后批准。批准前不启动采集。已连接的机器留空保留连接。"
        alert.addButton(withTitle: "保存并连接")
        alert.addButton(withTitle: "取消")
        let form = NSStackView()
        form.orientation = .vertical
        form.alignment = .leading
        form.spacing = 8
        form.frame = NSRect(x: 0, y: 0, width: 360, height: 190)
        let server = NSTextField(string: store.server)
        let token = NSSecureTextField(string: "")
        token.placeholderString = "新机器留空申请授权；已有连接留空保留"
        let defaultID = (ProcessInfo.processInfo.hostName + "-" + NSUserName()).map { char in
            char.isASCII && (char.isLetter || char.isNumber || char == "-") ? String(char) : "-"
        }.joined()
        let source = NSTextField(string: store.sourceID ?? defaultID)
        source.isEditable = store.sourceID == nil
        for (label, field) in [("服务地址", server), ("访问令牌", token), ("本机来源标识", source)] {
            form.addArrangedSubview(NSTextField(labelWithString: label))
            form.addArrangedSubview(field)
            field.widthAnchor.constraint(equalToConstant: 360).isActive = true
        }
        let login = NSButton(checkboxWithTitle: "登录时启动 App 并继续采集", target: nil, action: nil)
        login.state = .on
        form.addArrangedSubview(login)
        alert.accessoryView = form
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return false }
        do {
            let pairing = token.stringValue.isEmpty && !store.hasToken
            try store.configure(server: server.stringValue, token: token.stringValue, sourceID: source.stringValue, awaitingApproval: pairing)
            if pairing { requestEnrollment(); return false }
            wantsLoginItem = login.state == .on
            collectNow()
            return true
        } catch let error as CollectorSetupError {
            showError(error.localizedDescription)
        } catch { showError("保存连接失败，请检查本机用户目录是否可写。") }
        return false
    }

    private func command(_ arguments: [String], helperOverride: URL? = nil, administrator: Bool = false, acceptFailureOutput: Bool = false, completion: @escaping ([String: Any]?) -> Void) {
        let helper = helperOverride ?? Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/AIUsageCollector.app/Contents/MacOS/AIUsageCollector")
        var environment = ProcessInfo.processInfo.environment
        if administrator, let token = store.administratorToken {
            environment["AI_USAGE_DEVICE_ADMIN_TOKEN"] = token
        }
        let childEnvironment = environment
        Task {
            let data: Data? = await Task.detached {
                let child = Process()
                child.executableURL = helper
                child.arguments = ["--collector-cli"] + arguments
                child.environment = childEnvironment
                let output = Pipe()
                child.standardOutput = output
                child.standardError = FileHandle.nullDevice
                do {
                    try child.run()
                    let bytes = output.fileHandleForReading.readDataToEndOfFile()
                    child.waitUntilExit()
                    return child.terminationStatus == 0 || acceptFailureOutput ? bytes : nil
                } catch { return nil }
            }.value
            completion(data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })
        }
    }

    func requestEnrollment() {
        var args = ["devices", "enroll", "--server", store.server, "--read", "--pending", store.enrollmentURL.path]
        for source in store.sourceIDs { args += ["--source-id", source] }
        command(args) { [weak self] result in
            guard let self else { return }
            guard let code = result?["user_code"] as? String else {
                self.showError("无法申请授权，请检查服务端是否已启用设备注册。")
                return
            }
            let alert = NSAlert()
            alert.messageText = "配对码：" + code
            alert.informativeText = "请管理员核对这台机器、当前用户与来源标识后批准。批准后从菜单选择“检查本机授权”。申请有效期为十分钟。"
            alert.runModal()
        }
    }

    func checkEnrollment(completion: @escaping () -> Void) {
        command(["devices", "check", "--pending", store.enrollmentURL.path,
                 "--display-config", store.root.appendingPathComponent("config.json").path]) { [weak self] result in
            guard let self else { return }
            if result?["status"] as? String == "activated" {
                do { try self.store.setEnabled(true); self.start(); completion() }
                catch { self.showError("授权已批准，但无法启动本机采集。") }
            } else if result?["status"] as? String == "pending" {
                self.showError("申请尚未批准，请管理员核对配对码。")
            } else { self.showError("无法完成授权：申请可能过期、已拒绝或服务尚未升级。") }
        }
    }

    func manageEnrollments() {
        if store.administratorToken == nil {
            let alert = NSAlert()
            alert.messageText = "连接设备管理员"
            alert.informativeText = "管理员凭据由服务端 Ops 配置，只需在管理机器保存一次。现有采集器共享令牌不能批准新设备。"
            let secret = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 24))
            alert.accessoryView = secret
            alert.addButton(withTitle: "保存并管理")
            alert.addButton(withTitle: "取消")
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            do { try store.configureAdministrator(token: secret.stringValue) }
            catch { showError("无法保存管理员凭据。"); return }
        }
        command(["devices", "list", "--server", store.server], administrator: true) { [weak self] result in
            guard let self else { return }
            guard let requests = result?["requests"] as? [[String: Any]] else {
                self.showError("管理员凭据未配置或注册服务未启用。普通设备凭据不能批准其他设备。")
                return
            }
            if requests.isEmpty { self.showError("当前没有待批准的设备申请。"); return }
            for request in requests {
                guard let id = request["request_id"] as? String, let code = request["user_code"] as? String,
                      let machine = request["machine"] as? String, let user = request["os_user"] as? String,
                      let sources = request["source_ids"] as? [String], let reads = request["read_requested"] as? Bool else { continue }
                let alert = NSAlert()
                alert.messageText = "核对配对码：" + code
                alert.informativeText = "机器：\(machine)\n用户：\(user)\n来源：\(sources.joined(separator: ", "))\n权限：" + (reads ? "上报本机来源与读取汇总" : "仅上报本机来源")
                alert.addButton(withTitle: "批准这台设备")
                alert.addButton(withTitle: "跳过")
                alert.addButton(withTitle: "拒绝")
                let choice = alert.runModal()
                if choice == .alertSecondButtonReturn { continue }
                var args = ["devices", choice == .alertFirstButtonReturn ? "approve" : "deny", "--server", self.store.server, "--request-id", id]
                if choice == .alertFirstButtonReturn && reads { args.append("--read") }
                self.command(args, administrator: true) { [weak self] outcome in
                    if outcome == nil { self?.showError("设备处理失败：可能已过期或来源已被其他设备占用。") }
                }
            }
        }
    }

    func checkUpdates() {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
        command(["upgrade", "check", "--app-version", version], acceptFailureOutput: true) { [weak self] result in
            guard let self else { return }
            if result?["status"] as? String == "up_to_date" {
                let alert = NSAlert()
                alert.messageText = UpgradeCheckMessage.text(status: "up_to_date", errorType: nil)
                alert.runModal()
                return
            }
            guard result?["status"] as? String == "update_available", let target = result?["app_version"] as? String else {
                self.showError(UpgradeCheckMessage.text(status: result?["status"] as? String, errorType: result?["error_type"] as? String))
                return
            }
            let alert = NSAlert()
            alert.messageText = "更新 AI Usage 到 " + target
            alert.informativeText = "升级会暂时退出 App 并检查新版本上报。设备授权与本地缓冲数据保留，失败时恢复旧 App。"
            alert.addButton(withTitle: "更新并重启")
            alert.addButton(withTitle: "稍后")
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            do {
                // Run from a separate helper copy so replacing the App cannot invalidate this updater's runtime.
                let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("AIUsageUpdate-" + UUID().uuidString)
                try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                let helperApp = temporary.appendingPathComponent("AIUsageCollector.app")
                try FileManager.default.copyItem(at: Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/AIUsageCollector.app"), to: helperApp)
                self.command(["upgrade", "apply", "--app-version", version, "--app-path", Bundle.main.bundleURL.path, "--root", self.store.root.path],
                             helperOverride: helperApp.appendingPathComponent("Contents/MacOS/AIUsageCollector")) { [weak self] outcome in
                    try? FileManager.default.removeItem(at: temporary)
                    if outcome == nil { self?.showError("升级未完成，当前 App 与配置已保留，请检查更新结果。") }
                }
            } catch { self.showError("无法准备独立升级程序，当前 App 保持不变。") }
        }
    }

    private func showError(_ text: String) {
        let alert = NSAlert()
        alert.messageText = text
        alert.alertStyle = .warning
        alert.runModal()
    }
}
